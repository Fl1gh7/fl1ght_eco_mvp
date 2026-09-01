import sqlite3
import pandas as pd
import re
import os

DB_PATH = "database.db"
EXCEL_FILE = "iphone.xlsx"


def import_excel_to_sqlite():
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Файл {EXCEL_FILE} не найден в корне проекта!")
        return

    print("⏳ Читаем Excel-файл...")
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=0, header=None)
    except Exception as e:
        print(f"❌ Ошибка чтения Excel: {e}")
        return

    # строка 0 — название услуги (merged), строка 1 — копия или оригинал
    service_headers = df.iloc[0]
    quality_headers = df.iloc[1]

    current_service = ""
    filled_services = []
    for header in service_headers:
        val = str(header).strip()
        if val != "nan" and val != "":
            current_service = val
        filled_services.append(current_service)

    data_rows = df.iloc[2:]
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM prices")
    
    count = 0
    for _, row in data_rows.iterrows():
        tech_type = str(row[0]).strip()
        lineup = str(row[1]).strip()
        
        if tech_type in ['nan', 'None', 'тип_техники'] or lineup == 'nan':
            continue
            
        for i in range(4, len(row)):
            price_raw = str(row[i]).strip()
            if price_raw in ['nan', '-', '', '0', 'None']:
                continue
                
            price_digits = "".join(re.findall(r'\d+', price_raw))
            if not price_digits:
                continue
                
            service_name = filled_services[i]
            quality_raw = str(quality_headers[i]).strip().lower()
            
            quality = ""
            if "копия" in quality_raw: quality = "копия"
            elif "оригинал" in quality_raw: quality = "оригинал"
            
            item_name = f"{tech_type} {lineup}: {service_name}"
            if quality:
                item_name += f" ({quality})"
                
            try:
                cursor.execute("INSERT INTO prices (item, price) VALUES (?, ?)", (item_name, int(price_digits)))
                count += 1
            except sqlite3.IntegrityError:
                pass
                
    conn.commit()
    conn.close()
    print(f"✅ Успех! Загружено {count} позиций прайса в базу данных.")

if __name__ == "__main__":
    import_excel_to_sqlite()