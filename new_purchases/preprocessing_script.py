import pandas as pd
import re
import os

# --- КОНФИГУРАЦИЯ ---
# Папка, в которой лежат сырые заявки.
INPUT_FOLDER = 'new_purchases'
# Имя вашего сырого файла (ВХОДНОЙ файл). Может быть .csv или .xlsx. 
# Убедитесь, что это имя файла лежит ВНУТРИ папки new_purchases.
INPUT_FILENAME = 'new_purchase.xlsx'  # пример: 'purchase_data.csv' или 'purchase_data.xlsx'

# ПОЛНЫЙ ПУТЬ К ВХОДНОМУ ФАЙЛУ
INPUT_RAW_PATH = os.path.join(INPUT_FOLDER, INPUT_FILENAME)

# Имя файла, который ждет скрипт мэтчинга (ВЫХОДНОЙ файл, сохраняется рядом со скриптами)
OUTPUT_CLEAN_FILE = 'purchase_input.csv'

# СПРАВОЧНИК СИНОНИМОВ ДЛЯ АВТОМАТИЧЕСКОГО МАППИНГА КОЛОНОК
COLUMN_SYNONYMS = {
    'item_name_raw': ['наименование', 'предмет', 'описание', 'название', 'item', 'subject', 'name', 'product'],
    'quantity': ['количество', 'кол-во', 'объем', 'qty', 'count']
}
# ---------------------

def map_columns(df):
    """
    Автоматически находит и переименовывает колонки в DataFrame 
    согласно справочнику синонимов.
    """
    
    # Приводим все названия колонок к нижнему регистру для устойчивости
    lower_cols_map = {col.lower().replace('.', '').strip(): col for col in df.columns}
    
    column_mapping = {}
    found_cols = set()
    
    for target_col, synonyms in COLUMN_SYNONYMS.items():
        if target_col in column_mapping:
            continue
            
        for synonym in synonyms:
            for lower_name, original_name in lower_cols_map.items():
                if synonym in lower_name and original_name not in found_cols:
                    column_mapping[original_name] = target_col
                    found_cols.add(original_name)
                    print(f"   ✅ Найдено: '{original_name}' -> '{target_col}'")
                    break 
            if target_col in column_mapping.values():
                break

    if 'item_name_raw' not in column_mapping.values() or 'quantity' not in column_mapping.values():
        print("❌ Ошибка маппинга: Не удалось автоматически найти одну или обе обязательные колонки.")
        raise ValueError("Отсутствуют необходимые колонки после автоматической идентификации.")
        
    df_mapped = df.rename(columns=column_mapping)
    return df_mapped[['item_name_raw', 'quantity']].copy()

def load_raw_data(file_path):
    """
    Загружает сырой файл заявки, поддерживая CSV и XLSX форматы, и маппит колонки.
    """
    print(f"Загрузка сырого файла: {file_path}")
    
    _, ext = os.path.splitext(file_path.lower())
    
    try:
        if ext == '.csv':
            # Чтение CSV
            try:
                df = pd.read_csv(file_path, sep=';', encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, sep=';', encoding='windows-1251')
        elif ext in ['.xlsx', '.xls']:
            # Чтение Excel
            df = pd.read_excel(file_path)
        else:
            print(f"❌ Ошибка: Неподдерживаемый формат файла: {ext}.")
            return None
    except FileNotFoundError:
        print(f"❌ Ошибка: Файл '{file_path}' не найден. Проверьте имя и путь.")
        return None
    except Exception as e:
        print(f"❌ Критическая ошибка при загрузке: {e}")
        return None
    
    print(f"Загружено {len(df)} строк.")
    
    print("\nНачало автоматического маппинга колонок...")
    try:
        df_mapped = map_columns(df)
        return df_mapped
    except ValueError as e:
        print(f"Маппинг не удался: {e}")
        return None


def preprocess_data(df):
    """
    Очищает и стандартизирует колонки item_name_raw и quantity.
    """
    
    # 1. Очистка item_name_raw
    print("\n-> Очистка наименований от мусорных символов и префиксов...")
    
    df['item_name_raw'] = df['item_name_raw'].astype(str)
    
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'[\ufeff\u200b\uFEFF]', '', regex=True)
    
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'^[‹ЏЉ]екарственный препарат\s*', '', regex=True)
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'екарственный препарат', '', regex=True)
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'[‹ЏЉ]', '', regex=True) 
    
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'оваЯ', 'овая', regex=True)
    df['item_name_raw'] = df['item_name_raw'].str.replace(r'аЯ', 'а', regex=True)
    
    df['item_name_raw'] = df['item_name_raw'].str.strip()
    
    # 2. Стандартизация quantity
    print("-> Стандартизация колонки 'quantity' (извлечение только чисел)...")
    
    df['quantity'] = df['quantity'].astype(str)
    df['quantity'] = df['quantity'].str.replace(r'[^0-9]+', '', regex=True)
    
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0).astype(int)
    
    return df

def main():
    # Проверка на необходимую библиотеку для Excel
    if INPUT_FILENAME.lower().endswith(('.xlsx', '.xls')):
        try:
            import openpyxl 
        except ImportError:
            print("⚠️ Ошибка: Для обработки файлов Excel необходимо установить библиотеку openpyxl.")
            print("   Выполните команду в Терминале: pip install openpyxl")
            return

    # 1. Проверка наличия входной папки
    if not os.path.isdir(INPUT_FOLDER):
        print(f"*** ПРЕДУПРЕЖДЕНИЕ ***")
        print(f"Папка '{INPUT_FOLDER}' не найдена. Создайте её.")
        return

    # 2. Загрузка и автоматический маппинг данных
    df_raw = load_raw_data(INPUT_RAW_PATH)
    if df_raw is None:
        return

    # 3. Предобработка и очистка
    df_clean = preprocess_data(df_raw)

    # 4. Сохранение результата
    print(f"\nСохранение очищенного файла в {OUTPUT_CLEAN_FILE}...")
    df_clean.to_csv(OUTPUT_CLEAN_FILE, sep=';', index=False, encoding='utf-8')

    print("\n======================================")
    print("✅ УСПЕХ: Файл полностью подготовлен!")
    print(f"Очищенный файл '{OUTPUT_CLEAN_FILE}' готов для мэтчинга.")
    print("Теперь вы можете запустить ваш скрипт мэтчинга:")
    print("    python matching_script.py")
    print("======================================")
    
if __name__ == "__main__":
    main()