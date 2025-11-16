import streamlit as st
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

# --------------------------------------------------------------------
# 2.1 Вспомогательная функция для извлечения дозировки
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
        # Составные шаблоны могут возвращать до 4 групп (2 значения и 2 единицы)
        parts = [part for part in match if part] 
        compound_string = ""
        for i in range(0, len(parts), 2):
            if i + 1 < len(parts): # Проверка, чтобы не выйти за границы
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
# 2.2 Основная загрузка и очистка реестра (КЭШИРУЕМАЯ ФУНКЦИЯ)
# --------------------------------------------------------------------
@st.cache_data(show_spinner="Загрузка и стандартизация реестра...")
def load_and_prepare_register(uploaded_file):
    """
    Загружает, очищает и стандартизирует реестр ЛС. Кэшируется Streamlit.
    """
    try:
        # Чтение загруженного файла (Streamlit)
        register_df = pd.read_csv(uploaded_file, sep=';', encoding='utf-8') 
        
        # Добавление недостающих колонок
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
        
        return register_df, mnn_list
        
    except Exception as e:
        st.error(f"❌ Критическая ошибка при загрузке или обработке реестра: {e}")
        st.code(traceback.format_exc())
        return pd.DataFrame({col: [] for col in REGISTER_COLUMNS + ['dosage_standardized']}), []

# ---
# ====================================================================
# 3. ФУНКЦИИ ПАРСИНГА И СОПОСТАВЛЕНИЯ ЗАЯВКИ
# ====================================================================

def find_best_mnn(name_clean, mnn_list, mnn_threshold):
    """
    Находит лучшее совпадение МНН с использованием RapidFuzz.
    Принимает настраиваемый порог чувствительности.
    
    Используется fuzz.token_sort_ratio для более строгого сопоставления
    по лексемам (словам) без учета порядка, что лучше для МНН.
    """
    if not name_clean or not mnn_list:
        return 'неизвестно', 0.0

    best_match = process.extractOne(
        query=name_clean, 
        choices=mnn_list, 
        scorer=fuzz.token_sort_ratio, 
        score_cutoff=mnn_threshold 
    )
    
    if best_match:
        return best_match[0], best_match[1]
    return 'неизвестно', 0.0


def prepare_purchase_data(purchase_df, mnn_list, mnn_threshold, noise_words):
    """
    Очистка и стандартизация входных данных закупки, а также парсинг МНН.
    Принимает настраиваемый порог чувствительности МНН и список шумящих слов.
    """
    
    # 1. Очистка торгового наименования
    purchase_df['trade_name_clean'] = purchase_df['item_name_raw'].astype(str).str.replace(r'[\r\n\t\ufeff\xa0]', ' ', regex=True).str.lower()
    
    # А. УДАЛЕНИЕ ШУМЯЩИХ СЛОВ (custom removal)
    for word in noise_words:
        # Удаляем слово/фразу и заменяем на пробел, чтобы не склеить соседние слова
        purchase_df['trade_name_clean'] = purchase_df['trade_name_clean'].str.replace(word, ' ', regex=False)
    
    # Б. Стандартная очистка символов и пробелов
    purchase_df['trade_name_clean'] = purchase_df['trade_name_clean'].str.replace(r'[^\w\s]', ' ', regex=True)
    purchase_df['trade_name_clean'] = purchase_df['trade_name_clean'].str.replace(r'\s+', ' ', regex=True).str.strip().replace('', 'н/д')
    
    
    # 2. Парсинг Дозировки
    purchase_df['dosage_standardized'] = purchase_df['trade_name_clean'].apply(extract_dosage).str.strip() 
    
    # 3. Создание mnn_search_clean (удаление дозировки из названия для парсинга МНН)
    dosage_pattern = r'(\d+[,\.]?\d*)\s*(мкг/доза|мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)\s*[\+\/—]?\s*(\d+[,\.]?\d*)*\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)*'
    mnn_search_clean = purchase_df['trade_name_clean'].str.replace(dosage_pattern, ' ', flags=re.IGNORECASE, regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    
    
    # 4. Парсинг МНН (используем mnn_list из загруженного реестра)
    # ПЕРЕДАЧА ПОРОГА МНН
    mnn_results = mnn_search_clean.apply(lambda x: find_best_mnn(x, mnn_list, mnn_threshold)).apply(pd.Series)

    purchase_df['mnn_standardized'] = mnn_results[0].astype(str).str.strip().replace('', 'н/д')
    purchase_df['mnn_match_score'] = mnn_results[1] 
    
    purchase_df['dosage_standardized'].replace('', 'н/д', inplace=True) 
    # Колонка 'trade_name_clean' больше не нужна
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
        "Known_Threshold_Price_USD": default_price, 
        "Client_Price_USD": default_price, 
        "Match_Score": 0.0
    }]


def check_purchase_item(purchase_row, register_df, dosage_threshold):
    """
    Проверяет одну позицию закупки и возвращает СПИСОК ВСЕХ НАЙДЕННЫХ СОВПАДЕНИЙ.
    Принимает настраиваемый порог чувствительности дозировки.
    """

    mnn_std = purchase_row['mnn_standardized']
    dosage_std = purchase_row['dosage_standardized'] 
    
    # 1. Уровень 1: Точное Совпадение (МНН + СТАНДАРТИЗИРОВАННАЯ Дозировка)
    exact_match_results = register_df[
        (register_df['mnn'] == mnn_std) & 
        (register_df['dosage_standardized'] == dosage_std) 
    ]
    
    if not exact_match_results.empty:
        # Для точного совпадения берем только первую запись
        first_match = exact_match_results.iloc[0]
        return [{
            "Status": "Полное соответствие", 
            "Reg_Match_Name": first_match['mnn'], # <-- ИСПРАВЛЕНО: Выводим МНН из реестра
            "Reg_Dosage_Original": first_match['dosage'], 
            "Manufacturer": first_match['manufacturer'], 
            "Purchase_Price_USD": first_match['purchase_price_USD'], 
            "Known_Threshold_Price_USD": first_match['known_threshold_price_USD'], 
            "Client_Price_USD": first_match['client_price_USD'], 
            "Match_Score": 100.0
        }]

    # *** ИСПРАВЛЕНИЕ ЛОГИКИ: Если МНН не найден, сразу "Не найдено" ***
    if mnn_std == 'неизвестно':
        return check_purchase_item_not_found(purchase_row)
        
    filtered_df = register_df[register_df['mnn'] == mnn_std].copy() # Используем .copy() для безопасности

    # 2. Уровень 2: Нечеткий Поиск (Fuzzy Match) - ТОЛЬКО ПО ДОЗИРОВКЕ
    
    best_match_score = 0
    best_match_dosage = None
    
    # Ищем лучшую дозировку среди всех записей с найденным МНН
    if dosage_std != 'н/д':
        for index, row in filtered_df.iterrows():
            reg_dosage_std = row['dosage_standardized'] 
            if reg_dosage_std == 'н/д': continue
            
            # Используем token_set_ratio для гибкого сравнения дозировок
            score = fuzz.token_set_ratio(dosage_std, reg_dosage_std) 
            if score > best_match_score:
                best_match_score = score
                best_match_dosage = reg_dosage_std 
            
    # ИСПОЛЬЗОВАНИЕ ПЕРЕДАННОГО ПОРОГА ЧУВСТВИТЕЛЬНОСТИ ДОЗИРОВКИ
    if best_match_score >= dosage_threshold and best_match_dosage is not None:
        # Находим ВСЕ совпадения дозировки с лучшим результатом
        all_dosage_matches = filtered_df[filtered_df['dosage_standardized'] == best_match_dosage]
        
        results = []
        for index, row in all_dosage_matches.iterrows():
            results.append({
                "Status": "Потенциальное соответствие", 
                "Reg_Match_Name": row['mnn'], # <-- Выводим МНН из реестра
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
        # Возвращаем ВСЕ записи с найденным МНН
        results = []
        for index, row in filtered_df.iterrows():
            results.append({
                "Status": "Частичное соответствие МНН", 
                "Reg_Match_Name": row['mnn'], # <-- Выводим МНН из реестра
                "Reg_Dosage_Original": row['dosage'], 
                "Manufacturer": row['manufacturer'], 
                "Purchase_Price_USD": row['purchase_price_USD'], 
                "Known_Threshold_Price_USD": row['known_threshold_price_USD'], 
                "Client_Price_USD": row['client_price_USD'], 
                "Match_Score": purchase_row['mnn_match_score'] # Fuzzy Score МНН
            })
        return results
            
    
    # 4. Уровень 4: Не найдено 
    return check_purchase_item_not_found(purchase_row)


# ---
# ====================================================================
# 4. ФУНКЦИЯ ДЛЯ СТИЛИЗАЦИИ РЕЗУЛЬТАТОВ (Для экспорта в Excel)
# ====================================================================

def highlight_matches_row(row):
    """
    Применяет стили (зеленый/синий) к строкам на основе статуса.
    Зеленый - Полное соответствие.
    Синий - Частичное или Потенциальное соответствие.
    """
    
    green_style = 'background-color: #C6EFCE; color: #006100;' # Светло-зеленый
    blue_style = 'background-color: #BDD7EE; color: #000000;'   # Светло-синий
    no_style = ''

    if row['Status'] == 'Полное соответствие':
        style = green_style
    elif row['Status'] in ['Потенциальное соответствие', 'Частичное соответствие МНН']:
        # Объединяем Потенциальное и Частичное соответствие в один синий цвет
        style = blue_style
    else:
        style = no_style
        
    return [style] * len(row)


@st.cache_data(show_spinner="Формирование Excel-файла со стилями...")
def convert_df_to_excel(df_to_style):
    """Создает Excel-файл в памяти с примененной стилизацией."""
    output = io.BytesIO()
    
    # Создаем ExcelWriter для применения стилей
    writer = pd.ExcelWriter(output, engine='openpyxl')
    
    # Применяем стилизацию через pandas Styler
    styled_df = df_to_style.style.apply(highlight_matches_row, axis=1) 
    
    # Сохраняем стилизованный DataFrame
    styled_df.to_excel(writer, index=False, sheet_name='Matching_Results')
    
    # Закрываем writer и получаем байты
    writer.close()
    processed_data = output.getvalue()
    return processed_data


# ---
# ====================================================================
# 5. ГЛАВНЫЙ БЛОК STREAMLIT
# ====================================================================

def main():
    # Настройки страницы
    st.set_page_config(
        layout="wide", 
        page_title="Анализ Закупок ЛС", 
        menu_items={'About': 'Система сопоставления списка закупок с эталонным реестром.'}
    )
    
    st.title("💊 MatchSense")
    st.markdown("---")

    # --- НАСТРОЙКИ В БОКОВОМ МЕНЮ ---
    st.sidebar.header("⚙️ Настройки Чувствительности")
    
    # Ползунок для настройки порога МНН
    mnn_threshold = st.sidebar.slider(
        'Порог чувствительности МНН (0-100):',
        min_value=50,
        max_value=100,
        value=90, # ИЗМЕНЕНО: Значение по умолчанию 90
        step=5
    )
    st.sidebar.caption(f"Текущий порог для МНН: {mnn_threshold} (используется Token Sort Ratio)") # ИЗМЕНЕНО
    
    # Ползунок для настройки порога Дозировки
    dosage_threshold = st.sidebar.slider(
        'Порог чувствительности Дозировки (0-100):',
        min_value=50,
        max_value=100,
        value=75, # Значение по умолчанию
        step=5
    )
    st.sidebar.caption(f"Текущий порог для Дозировки: {dosage_threshold} (используется Token Set Ratio)")
    st.sidebar.markdown("---")
    
    # --- НАСТРОЙКА ОЧИСТКИ ТЕКСТА ---
    st.sidebar.header("🧹 Очистка Названий")
    
    noise_words_raw = st.sidebar.text_area(
        'Список слов/фраз для удаления (через запятую, нижний регистр):',
        value='упаковка, шт, в упаковке, box, pack, for injection',
        height=100,
        help="Эти слова будут удалены из 'item_name_raw' перед парсингом МНН и дозировки. Используйте нижний регистр."
    )
    # Парсинг списка слов для удаления
    noise_words = [word.strip() for word in noise_words_raw.lower().split(',') if word.strip()]
    
    st.sidebar.markdown("---")


    col1, col2 = st.columns(2)

    # --- 1. ЗАГРУЗКА РЕЕСТРА ---
    with col1:
        st.header("1. Эталонный Реестр") 
        uploaded_register_file = st.file_uploader(
            "Загрузите эталонный файл (register_ls.csv)", 
            type=['csv'],
            key="register_file"
        )

    # --- ИНИЦИАЛИЗАЦИЯ ДАННЫХ ---
    register_df = pd.DataFrame()
    mnn_list = []
    
    if uploaded_register_file is not None:
        # Загрузка и подготовка реестра (кэшируется)
        register_df, mnn_list = load_and_prepare_register(uploaded_register_file)
        
        if not register_df.empty:
            st.sidebar.success(f"Реестр загружен. Уникальных МНН: {len(mnn_list)}")
            st.sidebar.dataframe(register_df.head(3), use_container_width=True)
            
        else:
            st.warning("Загруженный реестр пуст или содержит ошибку.")
            return

    # --- 2. ЗАГРУЗКА ЗАЯВКИ И ОБРАБОТКА ---
    with col2:
        st.header("2. Список Закупок") # <-- Убрано название файла
        uploaded_purchase_file = st.file_uploader(
            "Загрузите файл для анализа (purchase_input.csv)", # <-- Убрано название файла из начала
            type=['csv'],
            key="purchase_file"
        )
        
    # Кнопка запуска анализа размещена ниже колонок загрузки
    analysis_ready = uploaded_purchase_file is not None and not register_df.empty
    
    # Флаг для запуска анализа
    run_analysis = False
    
    if analysis_ready:
        st.markdown("---")
        # Показываем кнопку только если файлы загружены
        if st.button('🚀 Запустить анализ / Обновить результаты', type="primary"):
            run_analysis = True
    else:
        st.info("Пожалуйста, загрузите оба файла (register_ls.csv и purchase_input.csv), чтобы активировать кнопку запуска.")
        return # Выход, если файлы не готовы
        

    if run_analysis: # Анализ запускается только по флагу run_analysis, который устанавливается кнопкой
        st.header("3. Результаты Анализа")
        
        try:
            # Чтение файла закупки
            purchase_df = pd.read_csv(uploaded_purchase_file, sep=';', encoding='utf-8')

            if purchase_df.empty:
                st.warning("Файл закупки пуст. Обработка остановлена.")
                return
            
            # Проверка наличия обязательной колонки
            if 'item_name_raw' not in purchase_df.columns:
                st.error("Ошибка: Файл закупки должен содержать колонку 'item_name_raw'.")
                return

            with st.spinner('⚙️ Выполняется предобработка, парсинг и многоуровневое сопоставление...'):
                # 1. Подготовка данных закупки (включая парсинг МНН, передачу порога МНН и список шумящих слов)
                purchase_df = prepare_purchase_data(purchase_df, mnn_list, mnn_threshold, noise_words)
                
                # 2. Запуск сопоставления (передача порога дозировки)
                purchase_df['Matches'] = purchase_df.apply(
                    lambda row: check_purchase_item(row, register_df, dosage_threshold), 
                    axis=1
                )

                # 3. Денормализация (размножение строк для всех совпадений)
                all_results_df = purchase_df.explode('Matches').reset_index(drop=True)
                match_details = all_results_df['Matches'].apply(pd.Series)
                final_df = pd.concat([all_results_df.drop(columns=['Matches']), match_details], axis=1)
                
                # Удаляем промежуточные колонки
                final_df = final_df.drop(columns=['mnn_standardized', 'dosage_standardized', 'mnn_match_score'], errors='ignore')

            st.success("✅ Сопоставление завершено! Найдено совпадений: " + str(len(final_df)))

            # --- ВЫВОД РЕЗУЛЬТАТА ---
            display_cols = ['item_name_raw', 'quantity', 'Status', 'Reg_Match_Name', 'Reg_Dosage_Original', 'Manufacturer', 
                            'Purchase_Price_USD', 'Known_Threshold_Price_USD', 'Client_Price_USD', 'Match_Score']
            
            st.subheader("Предварительный просмотр результата:")
            # Здесь Streamlit отобразит таблицу со стилями, примененными через .style
            st.dataframe(final_df[display_cols].style.apply(highlight_matches_row, axis=1), use_container_width=True)

            # --- КНОПКА ЭКСПОРТА ---
            excel_data = convert_df_to_excel(final_df)
            
            st.download_button(
                label="⬇️ Скачать Результаты в Excel (со стилями)",
                data=excel_data,
                file_name=f'matching_results_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Произошла ошибка при обработке файла закупки. Убедитесь, что разделитель — ';': {e}")
            st.code(traceback.format_exc())

if __name__ == '__main__':
    main()