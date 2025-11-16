import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz import process 
import re
import os 
import datetime
import io 
import traceback

# ====================================================================
# 1. КОНСТАНТЫ И ЗАГРУЗКА РЕЕСТРА ЛС (МНН, Дозировка)
# ====================================================================

REGISTER_COLUMNS = ['mnn', 'trade_name', 'dosage', 'form', 'manufacturer', 'purchase_price_USD', 'known_threshold_price_USD', 'client_price_USD']
mnn_list = []
REGISTER_FILENAME = 'register_ls.csv' 
PURCHASE_FILENAME = 'purchase_input.csv' 

# --------------------------------------------------------------------
# 2.1 Вспомогательная функция для извлечения дозировки (Снова ИСПРАВЛЕННАЯ)
# --------------------------------------------------------------------
def extract_dosage(name):
    """
    Извлекает все дозировки, включая концентрации, и стандартизирует их.
    Использует более простую логику для надежности.
    """
    # 1. Шаблон для концентраций: 0,5 мг/мл, 50 мг/мл и т.п.
    concentration_pattern = r'(\d+[,\.]?\d*)\s*(мг|ед|г|мкг|МО|МЕ|%|mg|g|mcg|IU)\s*\/\s*(мл|доза|ml|l|mcl)' 
    
    # 2. Шаблон для составных: 120 мг + 60 мг, или 500 мг в 100 мл
    compound_pattern = r'(\d+[,\.]?\d*)\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)\s*[\+\/—]\s*(\d+[,\.]?\d*)\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)'
    
    # 3. Шаблон для простых: 100 мг, 10 мл
    simple_pattern = r'(\d+[,\.]?\d*)\s*(мкг/доза|мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)'
    
    all_matches = []
    
    # A. Поиск концентраций (приоритет)
    for match in re.findall(concentration_pattern, name, re.IGNORECASE):
        val1, unit1, unit2 = match
        all_matches.append(f"{val1.replace('.', ',')} {unit1.lower()}/{unit2.lower()}")

    # B. Поиск составных дозировок (приоритет)
    for match in re.findall(compound_pattern, name, re.IGNORECASE):
        parts = [part for part in match if part] 
        compound_string = ""
        for i in range(0, len(parts), 2):
            if compound_string:
                compound_string += " + "
            compound_string += f"{parts[i].replace('.', ',')} {parts[i+1].lower()}"
        all_matches.append(compound_string)

    # C. Поиск простых дозировок (если не было найдено сложной)
    if not all_matches:
        for val, unit in re.findall(simple_pattern, name, re.IGNORECASE):
            all_matches.append(f"{val.replace('.', ',')} {unit.lower()}")

    # Удаление дубликатов и сортировка
    unique_matches = sorted(list(set(all_matches)))
            
    return ", ".join(unique_matches) if unique_matches else 'н/д'

# --------------------------------------------------------------------
# 2.2 Основная загрузка и очистка реестра
# --------------------------------------------------------------------

try:
    print(f"🔍 Попытка загрузки реестра: {REGISTER_FILENAME}...")
    
    register_df = pd.read_csv(REGISTER_FILENAME, sep=';', encoding='utf-8') 
    
    for col in REGISTER_COLUMNS:
        if col not in register_df.columns:
            if 'price_USD' in col: 
                register_df[col] = 0.0
            else:
                register_df[col] = 'Н/Д' 
    
    # АГРЕССИВНАЯ ОЧИСТКА МНН
    register_df['mnn'] = register_df['mnn'].astype(str)
    register_df['mnn'] = register_df['mnn'].str.replace(r'[\r\n\t\ufeff\xa0]', ' ', regex=True).str.lower()
    register_df['mnn'] = register_df['mnn'].str.replace(r'[^\w\s]', ' ', regex=True) 
    register_df['mnn'] = register_df['mnn'].str.replace(r'\s+', ' ', regex=True).str.strip()


    # Стандартизация дозировки
    register_df['dosage_standardized'] = register_df['dosage'].astype(str).apply(extract_dosage).str.strip()

    mnn_list = register_df['mnn'].unique().tolist()
    
    print(f"✅ Реестр загружен. Уникальных МНН: {len(mnn_list)}\n")
    
except FileNotFoundError:
    print(f"❌ Критическая ошибка: Файл реестра '{REGISTER_FILENAME}' не найден. Проверьте имя!")
    register_df = pd.DataFrame({col: [] for col in REGISTER_COLUMNS + ['dosage_standardized']})
except Exception as e:
    print(f"❌ Критическая ошибка при загрузке или обработке реестра: {e}")
    traceback.print_exc()
    register_df = pd.DataFrame({col: [] for col in REGISTER_COLUMNS + ['dosage_standardized']})

# ---
# ====================================================================
# 3. ФУНКЦИИ ПАРСИНГА И СОПОСТАВЛЕНИЯ ЗАЯВКИ
# ====================================================================

def find_best_mnn(name_clean, mnn_list):
    """
    Находит лучшее совпадение МНН с использованием RapidFuzz."""
    if not name_clean or not mnn_list:
        return 'неизвестно', 0.0

    best_match = process.extractOne(
        query=name_clean, 
        choices=mnn_list, 
        scorer=fuzz.WRatio, 
        score_cutoff=80 
    )
    
    if best_match:
        return best_match[0], best_match[1]
    return 'неизвестно', 0.0


def prepare_purchase_data(purchase_df):
    """Очистка и стандартизация входных данных закупки."""
    
    purchase_df['trade_name_clean'] = purchase_df['item_name_raw'].astype(str).str.replace(r'[\r\n\t\ufeff\xa0]', ' ', regex=True).str.lower()
    purchase_df['trade_name_clean'] = purchase_df['trade_name_clean'].str.replace(r'[^\w\s]', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip().replace('', 'н/д')
    
    # 2. Парсинг Дозировки
    purchase_df['dosage_standardized'] = purchase_df['trade_name_clean'].apply(extract_dosage).str.strip() 
    
    # 3. Создание mnn_search_clean (для чистого парсинга МНН)
    dosage_pattern = r'(\d+[,\.]?\d*)\s*(мкг/доза|мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)\s*[\+\/—]?\s*(\d+[,\.]?\d*)*\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)*'
    mnn_search_clean = purchase_df['trade_name_clean'].str.replace(dosage_pattern, ' ', flags=re.IGNORECASE, regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    
    
    # 4. Парсинг МНН
    mnn_results = mnn_search_clean.apply(lambda x: find_best_mnn(x, mnn_list)).apply(pd.Series)

    purchase_df['mnn_standardized'] = mnn_results[0].astype(str).str.strip().replace('', 'н/д')
    purchase_df['mnn_match_score'] = mnn_results[1] 
    
    purchase_df['dosage_standardized'].replace('', 'н/д', inplace=True) 
    purchase_df.drop(columns=['trade_name_clean'], errors='ignore', inplace=True) 
    
    return purchase_df

def check_purchase_item_not_found(purchase_row):
    """Создает стандартную строку 'Не найдено'."""
    default_manufacturer = "Н/Д"
    default_price = 0.0
    return [{
        "Status": "Не найдено", 
        "Reg_Match_Name": "Нет соответствий", 
        "Reg_Dosage_Original": "Н/Д", 
        "Manufacturer": default_manufacturer, 
        "Purchase_Price_USD": default_price, 
        "Threshold_Price_USD": default_price, 
        "Client_Price_USD": default_price, 
        "Match_Score": 0.0
    }]


def check_purchase_item(purchase_row, register_df):
    """
    Проверяет одну позицию закупки и возвращает СПИСОК ВСЕХ НАЙДЕННЫХ СОВПАДЕНИЙ.
    """

    mnn_std = purchase_row['mnn_standardized']
    dosage_std = purchase_row['dosage_standardized'] 
    
    # 1. Уровень 1: Точное Совпадение (МНН + СТАНДАРТИЗИРОВАННАЯ Дозировка)
    exact_match_results = register_df[
        (register_df['mnn'] == mnn_std) & 
        (register_df['dosage_standardized'] == dosage_std) 
    ]
    
    if not exact_match_results.empty:
        first_match = exact_match_results.iloc[0]
        return [{
            "Status": "Полное соответствие", 
            "Reg_Match_Name": first_match['trade_name'], 
            "Reg_Dosage_Original": first_match['dosage'], 
            "Manufacturer": first_match['manufacturer'], 
            "Purchase_Price_USD": first_match['purchase_price_USD'], 
            "Known_Threshold_Price_USD": first_match['known_threshold_price_USD'], 
            "Client_Price_USD": first_match['client_price_USD'], 
            "Match_Score": 100.0
        }]

    # 2. Уровень 2: Нечеткий Поиск (Fuzzy Match) - ТОЛЬКО ПО ДОЗИРОВКЕ
    
    FUZZY_THRESHOLD = 75.0 
    best_match_score = 0
    
    # *** ИСПРАВЛЕНИЕ ЛОГИКИ: Если МНН не найден, пропускаем Уровень 2 и 3, сразу "Не найдено" ***
    if mnn_std == 'неизвестно':
        return check_purchase_item_not_found(purchase_row)
        
    filtered_df = register_df[register_df['mnn'] == mnn_std] 

    # Ищем лучшую дозировку среди всех записей с найденным МНН
    for index, row in filtered_df.iterrows():
        reg_dosage_std = row['dosage_standardized'] 
        if dosage_std == 'н/д' or reg_dosage_std == 'н/д': continue
        score = fuzz.token_set_ratio(dosage_std, reg_dosage_std) 
        if score > best_match_score:
            best_match_score = score
            best_match_dosage = row['dosage_standardized'] # Сохраняем лучшую стандартизированную дозировку
            
    if best_match_score >= FUZZY_THRESHOLD:
        # Находим ВСЕ совпадения дозировки
        all_dosage_matches = filtered_df[filtered_df['dosage_standardized'] == best_match_dosage]
        
        results = []
        for index, row in all_dosage_matches.iterrows():
             results.append({
                "Status": "Потенциальное соответствие", 
                "Reg_Match_Name": row['trade_name'], 
                "Reg_Dosage_Original": row['dosage'], 
                "Manufacturer": row['manufacturer'], 
                "Purchase_Price_USD": row['purchase_price_USD'], 
                "Known_Threshold_Price_USD": row['known_threshold_price_USD'], 
                "Client_Price_USD": row['client_price_USD'], 
                "Match_Score": best_match_score # Fuzzy Score Дозировки
            })
        return results
    
    
    # 3. Уровень 3: Частичное соответствие по МНН (дозировка не совпала или отсутствует)
    if mnn_std != 'неизвестно':
        mnn_matches = register_df[register_df['mnn'] == mnn_std]
        
        if not mnn_matches.empty:
            results = []
            for index, row in mnn_matches.iterrows():
                results.append({
                    "Status": "Частичное соответствие МНН", 
                    "Reg_Match_Name": row['trade_name'], 
                    "Reg_Dosage_Original": row['dosage'], 
                    "Manufacturer": row['manufacturer'], 
                    "Purchase_Price_USD": row['purchase_price_USD'], 
                    "Known_Threshold_Price_USD": row['known_threshold_price_USD'], 
                    "Client_Price_USD": row['client_price_USD'], 
                    "Match_Score": purchase_row['mnn_match_score'] # Fuzzy Score МНН
                })
            return results
            
    
    # 4. Уровень 4: Не найдено (Должно быть отловлено в начале Уровня 2)
    return check_purchase_item_not_found(purchase_row)


# ---
# ====================================================================
# 4. ФУНКЦИЯ ДЛЯ СТИЛИЗАЦИИ РЕЗУЛЬТАТОВ
# ====================================================================

def highlight_matches_row(row):
    """Применяет стили (зеленый/желтый/синий) к строкам на основе статуса."""
    
    green_style = 'background-color: #C6EFCE; color: #006100;' 
    yellow_style = 'background-color: #FFEB9C; color: #9C6500;' 
    blue_style = 'background-color: #BDD7EE; color: #000000;' # Частичное соответствие МНН
    no_style = ''

    if row['Status'] == 'Полное соответствие':
        style = green_style
    elif row['Status'] == 'Потенциальное соответствие':
        style = yellow_style
    elif row['Status'] == 'Частичное соответствие МНН':
        style = blue_style
    else:
        style = no_style
        
    return [style] * len(row)

# ---
# ====================================================================
# 5. ГЛАВНЫЙ ИСПОЛНЯЕМЫЙ БЛОК
# ====================================================================

if __name__ == '__main__':
    try:
        # --- ЗАГРУЗКА ФАЙЛА ЗАЯВКИ ---
        try:
            purchase_df = pd.read_csv(PURCHASE_FILENAME, sep=';', encoding='utf-8')
        except FileNotFoundError:
            print(f"❌ Ошибка: Файл '{PURCHASE_FILENAME}' не найден.")
            exit()

        if purchase_df.empty:
            print(f"⚠️ Внимание: Файл '{PURCHASE_FILENAME}' пуст. Прекращение работы.")
            exit()
            
        # --- ПРЕДОБРАБОТКА ДАННЫХ ---
        purchase_df = prepare_purchase_data(purchase_df)

        # --- ДИАГНОСТИКА: ПАРСИНГ МНН (ВРЕМЕННЫЙ ВЫВОД) ---
        print("\n=== ДИАГНОСТИКА: ПАРСИНГ МНН и ДОЗИРОВКИ ===")
        print(purchase_df[['item_name_raw', 'mnn_standardized', 'dosage_standardized', 'mnn_match_score']])
        print("========================================\n")
        
        # --- ЗАПУСК СОПОСТАВЛЕНИЯ И ДЕНОРМАЛИЗАЦИЯ (РАЗМНОЖЕНИЕ СТРОК) ---
        print("⚙️ Запуск сопоставления...")
        
        purchase_df['Matches'] = purchase_df.apply(lambda row: check_purchase_item(row, register_df), axis=1)

        all_results_df = purchase_df.explode('Matches').reset_index(drop=True)
        
        match_details = all_results_df['Matches'].apply(pd.Series)
        
        final_df = pd.concat([all_results_df.drop(columns=['Matches']), match_details], axis=1)

        final_df = final_df.drop(columns=['mnn_standardized', 'dosage_standardized', 'mnn_match_score'], errors='ignore')
        
        # --- ВЫВОД РЕЗУЛЬТАТА НА ЭКРАН ---
        print("\n=== РЕЗУЛЬТАТ АНАЛИЗА СПИСКА ЗАКУПОК (Построчный вывод) ===")
        print(final_df[['item_name_raw', 'quantity', 'Status', 'Reg_Match_Name', 'Reg_Dosage_Original', 'Manufacturer', 
                        'Purchase_Price_USD', 'Threshold_Price_USD', 'Client_Price_USD', 'Match_Score']])
        print("========================================\n")

        # --- ЭКСПОРТ В EXCEL (С СТИЛИЗАЦИЕЙ) ---
        EXPORT_FOLDER = 'export_results'
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        EXPORT_FILENAME = f'matching_results_{timestamp}.xlsx'
        EXPORT_PATH = os.path.join(EXPORT_FOLDER, EXPORT_FILENAME)

        if not os.path.exists(EXPORT_FOLDER):
            os.makedirs(EXPORT_FOLDER)

        try:
            styled_df = final_df.style.apply(highlight_matches_row, axis=1)
            styled_df.to_excel(EXPORT_PATH, index=False, engine='openpyxl')
            
            print(f"✅ Результаты успешно сохранены в файл: {EXPORT_PATH} (Включая цветовое выделение)")
        except ImportError:
            print("⚠️ Ошибка: Для экспорта в Excel со стилями необходимо установить библиотеку openpyxl.")
            print("   Выполните команду в Терминале: pip install openpyxl")

    except Exception as e:
        # Ловит все остальные необработанные ошибки 
        print(f"\n❌ Критическая ошибка в главном блоке обработки: {e}")
        traceback.print_exc()