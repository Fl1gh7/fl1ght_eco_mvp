"""Консольный прогон воронки: Сито → прайс → Продавец → SQLite."""
import asyncio
from services.ai.sieve import ai_sieve
from services.ai.closer import ai_closer
from services.ai.matcher import search_prices_in_db
from core import db_manager

async def main():
    print("=" * 65)
    print("Конвейер: Сито → прайс → Продавец → SQLite")
    print("=" * 65 + "\n")
    
    chat_history = []
    
    customer_id = db_manager.get_or_create_customer(platform="console", external_id="tester_1", name="Тестер")
    
    while True:
        user_text = input("👤 Входящее сообщение (Лид): ")
        if user_text.lower() in ['выход', 'exit', 'quit']:
            break
            
        if not chat_history:
            print("⏳ [Сито] Проверяем на спам...")
            sieve_result = await ai_sieve.analyze_lead(user_text)
            
            db_manager.save_lead(customer_id, user_text, sieve_result['score'], sieve_result['status'])
            
            if sieve_result['status'] == 'trash':
                print(f"🗑️ [Сито] Отклонено ({sieve_result['score']}/100). Причина: {sieve_result['reason']}\n")
                continue 
                
            print(f"✅ [Сито] Целевой запрос ({sieve_result['score']}/100)! Передаем в отдел продаж.")
            
            db_manager.update_order_status(customer_id, "new")
        
        chat_history.append({"role": "user", "text": user_text})
        
        print("🔍 [Матчер] Подбираем цены из прайса...")
        real_prices = search_prices_in_db(user_text)
        
        print("🧠 [Продавец] Печатает ответ...")
        closer_result = await ai_closer.generate_response(chat_history, real_prices)
        
        ai_reply = closer_result.get('reply_text', 'Ошибка генерации')
        action = closer_result.get('action', 'active')
        
        db_manager.update_order_status(customer_id, action)
        
        print(f"\n🤖 Продавец: {ai_reply}")
        print(f"⚙️ [Воронка] Текущий статус: {action.upper()} (💾 Сохранено в БД)\n")
        
        chat_history.append({"role": "assistant", "text": ai_reply})
        
        if action in ['success', 'delayed']:
            print(f"🏁 Диалог завершен. Готов принять следующего клиента!\n")
            print("-" * 65)
            chat_history.clear()
            
            import uuid
            new_id = str(uuid.uuid4())[:8]
            customer_id = db_manager.get_or_create_customer(platform="console", external_id=new_id, name="Новый Тестер")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Система остановлена.")