import streamlit as st
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz import process 
import re
import io 
import plotly.express as px
import numpy as np

# ====================================================================
# 1. КОНСТАНТЫ И ФУНКЦИИ ОБРАБОТКИ
# ====================================================================

# --- ФИКСИРОВАННЫЙ РАЗДЕЛИТЕЛЬ ---
CSV_SEPARATOR = ';'
# --- ФИКСИРОВАННЫЙ СПИСОК РЕЗУЛЬТИРУЮЩИХ КОЛОНОК ---
FINAL_COLUMNS = [
    'item_name_raw', 
    'quantity', 
    'Status', 
    'Reg_Match_Name', 
    'Reg_Dosage_Original', 
    'Manufacturer', 
    'Purchase_Price_USD', 
    'Known_Threshold_Price_USD', 
    'Client_Price_USD', 
    'Match_Score',
    'Price_Difference_USD', # Цена клиента - Пороговая цена (положительно = переплата)
    'Potential_Saving_USD' # Разница * Quantity (Суммарная потенциальная экономия)
]

# --------------------------------------------------------------------
# 1.1 Вспомогательная функция для извлечения дозировки
# --------------------------------------------------------------------
def extract_dosage(name):
    """
    Извлекает все дозировки, включая концентрации, и стандартизирует их.
    """
    concentration_pattern = r'(\d+[,\.]?\d*)\s*(мг|ед|г|мкг|МО|МЕ|%|mg|g|mcg|IU)\s*\/\s*(мл|доза|ml|l|mcl)' 
    compound_pattern = r'(\d+[,\.]?\d*)\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)\s*[\+\/—]\s*(\d+[,\.]?\d*)\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)'
    simple_pattern = r'(\d+[,\.]?\d*)\s*(мкг/доза|мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)'
    
    all_matches = []
    
    for match in re.findall(concentration_pattern, name, re.IGNORECASE):
        val1, unit1, unit2 = match
        all_matches.append(f"{val1.replace('.', ',')} {unit1.lower()}/{unit2.lower()}")

    for match in re.findall(compound_pattern, name, re.IGNORECASE):
        parts = [part for part in match if part] 
        compound_string = ""
        for i in range(0, len(parts), 2):
            if compound_string: compound_string += " + "
            compound_string += f"{parts[i].replace('.', ',')} {parts[i+1].lower()}"
        all_matches.append(compound_string)

    if not all_matches:
        for val, unit in re.findall(simple_pattern, name, re.IGNORECASE):
            all_matches.append(f"{val.replace('.', ',')} {unit.lower()}")

    unique_matches = sorted(list(set(all_matches)))
            
    return ", ".join(unique_matches) if unique_matches else 'н/д'


# --------------------------------------------------------------------
# 1.2 Функция поиска МНН
# --------------------------------------------------------------------
def find_best_mnn(name_clean, mnn_list, score_cutoff):
    """
    Находит наиболее вероятный МНН в эталонном списке с настраиваемым порогом.
    """
    if not name_clean or not mnn_list:
        return 'неизвестно', 0.0

    best_match = process.extractOne(
        query=name_clean, 
        choices=mnn_list, 
        scorer=fuzz.WRatio, 
        score_cutoff=score_cutoff
    )
    
    if best_match:
        return best_match[0], best_match[1]
    return 'неизвестно', 0.0

# --------------------------------------------------------------------
# 1.3 Вспомогательная функция для "Не найдено"
# --------------------------------------------------------------------
def check_purchase_item_not_found():
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
        "Match_Score": 0.0,
        "Price_Difference_USD": 0.0,
        "Potential_Saving_USD": 0.0 
    }]

# --------------------------------------------------------------------
# 1.4 Основная функция сопоставления (ДОБАВЛЕН РАСЧЕТ ЦЕН)
# --------------------------------------------------------------------
def calculate_price_metrics(row, purchase_quantity):
    """Рассчитывает разницу и потенциальную экономию."""
    
    try:
        # Получаем данные безопасно (если колонки нет, вернет 0.0)
        client_price_raw = row.get('Client_Price_USD', 0.0) 
        threshold_price_raw = row.get('Known_Threshold_Price_USD', 0.0)
        
        # Конвертируем в float
        client_price = float(str(client_price_raw).replace(',', '.'))
        threshold_price = float(str(threshold_price_raw).replace(',', '.'))
        # Защита от NaN и некорректных значений в quantity
        quantity = int(purchase_quantity) if pd.notnull(purchase_quantity) else 0
    except (ValueError, TypeError):
        # Если цены или количество не парсятся, возвращаем нули
        return 0.0, 0.0

    # Разница в цене за единицу: Цена клиента - Пороговая цена (положительное = переплата)
    price_diff = client_price - threshold_price
    
    # Суммарная экономия (Разница * Количество)
    potential_saving = price_diff * quantity
    
    return price_diff, potential_saving


def check_purchase_item(purchase_row, register_df, fuzzy_threshold):
    """
    Проверяет одну позицию закупки и возвращает СПИСОК ВСЕХ НАЙДЕННЫХ СОВПАДЕНИЙ.
    """
    mnn_std = purchase_row['mnn_standardized']
    dosage_std = purchase_row['dosage_standardized']
    purchase_quantity = purchase_row['quantity']

    
    # 1. Уровень 1: Точное Совпадение (МНН + СТАНДАРТИЗИРОВАННАЯ Дозировка)
    exact_match_results = register_df[
        (register_df['mnn'] == mnn_std) & 
        (register_df['dosage_standardized'] == dosage_std) 
    ]
    
    if not exact_match_results.empty:
        first_match = exact_match_results.iloc[0]
        price_diff, saving = calculate_price_metrics(first_match, purchase_quantity)

        return [{
            "Status": "Полное соответствие", 
            "Reg_Match_Name": first_match['trade_name'], 
            "Reg_Dosage_Original": first_match['dosage'], 
            "Manufacturer": first_match['manufacturer'], 
            "Purchase_Price_USD": first_match['purchase_price_USD'], 
            "Known_Threshold_Price_USD": first_match['known_threshold_price_USD'], 
            "Client_Price_USD": first_match['client_price_USD'], 
            "Match_Score": 100.0,
            "Price_Difference_USD": price_diff, 
            "Potential_Saving_USD": saving 
        }]

    if mnn_std == 'неизвестно':
        return check_purchase_item_not_found()
        
    filtered_df = register_df[register_df['mnn'] == mnn_std] 


    # 2. Уровень 2: Нечеткий Поиск (Fuzzy Match) - ТОЛЬКО ПО ДОЗИРОВКЕ
    
    best_match_score = 0
    best_match_dosage = ""
    
    for index, row in filtered_df.iterrows():
        reg_dosage_std = row['dosage_standardized'] 
        if dosage_std == 'н/д' or reg_dosage_std == 'н/д': continue
        score = fuzz.token_set_ratio(dosage_std, reg_dosage_std) 
        if score > best_match_score:
            best_match_score = score
            best_match_dosage = row['dosage_standardized'] 
            
    if best_match_score >= fuzzy_threshold:
        all_dosage_matches = filtered_df[filtered_df['dosage_standardized'] == best_match_dosage]
        
        results = []
        for index, row in all_dosage_matches.iterrows():
             price_diff, saving = calculate_price_metrics(row, purchase_quantity)

             results.append({
                "Status": "Потенциальное соответствие", 
                "Reg_Match_Name": row['trade_name'], 
                "Reg_Dosage_Original": row['dosage'], 
                "Manufacturer": row['manufacturer'], 
                "Purchase_Price_USD": row['purchase_price_USD'], 
                "Known_Threshold_Price_USD": row['known_threshold_price_USD'], 
                "Client_Price_USD": row['client_price_USD'], 
                "Match_Score": best_match_score,
                "Price_Difference_USD": price_diff, 
                "Potential_Saving_USD": saving 
            })
        return results
    
    
    # 3. Уровень 3: Частичное соответствие по МНН (Расчет по первому найденному)
    if not filtered_df.empty:
        results = []
        for index, row in filtered_df.iterrows():
             price_diff, saving = calculate_price_metrics(row, purchase_quantity)

             results.append({
                "Status": "Частичное соответствие МНН", 
                "Reg_Match_Name": row['trade_name'], 
                "Reg_Dosage_Original": row['dosage'], 
                "Manufacturer": row['manufacturer'], 
                "Purchase_Price_USD": row['purchase_price_USD'], 
                "Known_Threshold_Price_USD": row['known_threshold_price_USD'], 
                "Client_Price_USD": row['client_price_USD'], 
                "Match_Score": purchase_row['mnn_match_score'],
                "Price_Difference_USD": price_diff, 
                "Potential_Saving_USD": saving 
            })
        return results
            
    return check_purchase_item_not_found()

# --------------------------------------------------------------------
# 1.5 ГЛАВНАЯ ФУНКЦИЯ ОБРАБОТКИ
# --------------------------------------------------------------------
def clean_column_names(df):
    """Очищает названия колонок: удаляет пробелы, невидимые символы и BOM."""
    df.columns = df.columns.str.strip().str.replace('\ufeff', '', regex=False)
    return df

def process_matching(purchase_df_raw, register_df_raw, fuzzy_threshold, mnn_score_cutoff):
    """Выполняет полную цепочку обработки с настраиваемыми параметрами."""
    
    # --- 0. ЗАЩИТА КОЛОНОК ---
    register_df = clean_column_names(register_df_raw.copy())
    purchase_df = clean_column_names(purchase_df_raw.copy())

    
    # --- 1. Очистка и стандартизация Реестра ---
    register_df['mnn'] = register_df['mnn'].astype(str).str.replace(r'[\r\n\t\ufeff\xa0]', ' ', regex=True).str.lower()
    register_df['mnn'] = register_df['mnn'].str.replace(r'[^\w\s]', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    register_df['dosage_standardized'] = register_df['dosage'].astype(str).apply(extract_dosage).str.strip()
    
    mnn_list = register_df['mnn'].unique().tolist()
    
    # --- 2. Очистка и парсинг Закупки ---
    
    # 2.1 Очистка 'quantity'
    if 'quantity' in purchase_df.columns:
         # Заменяем запятые на точки и приводим к int (после float, чтобы корректно обработать 10,0)
         purchase_df['quantity'] = purchase_df['quantity'].astype(str).str.replace(',', '.').apply(lambda x: int(float(x)) if pd.notnull(x) and str(x).replace('.', '', 1).isdigit() else 0)
    else:
        # Если колонка отсутствует или некорректна, заполняем нулями
        purchase_df['quantity'] = 0
        
    purchase_df['trade_name_clean'] = purchase_df['item_name_raw'].astype(str).str.replace(r'[\r\n\t\ufeff\xa0]', ' ', regex=True).str.lower()
    purchase_df['trade_name_clean'] = purchase_df['trade_name_clean'].str.replace(r'[^\w\s]', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip().replace('', 'н/д')
    
    purchase_df['dosage_standardized'] = purchase_df['trade_name_clean'].apply(extract_dosage).str.strip() 
    
    dosage_pattern = r'(\d+[,\.]?\d*)\s*(мкг/доза|мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)\s*[\+\/—]?\s*(\d+[,\.]?\d*)*\s*(мг|ед|мл|г|мкг|МО|МЕ|%|mg|ml|g|mcg|IU)*'
    mnn_search_clean = purchase_df['trade_name_clean'].str.replace(dosage_pattern, ' ', flags=re.IGNORECASE, regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    
    mnn_results = mnn_search_clean.apply(lambda x: find_best_mnn(x, mnn_list, mnn_score_cutoff)).apply(pd.Series)
    
    purchase_df['mnn_standardized'] = mnn_results[0].astype(str).str.strip().replace('', 'н/д')
    purchase_df['mnn_match_score'] = mnn_results[1] 
    
    # --- 3. Сопоставление и Денормализация ---
    purchase_df['Matches'] = purchase_df.apply(lambda row: check_purchase_item(row, register_df, fuzzy_threshold), axis=1)

    all_results_df = purchase_df.explode('Matches').reset_index(drop=True)
    match_details = all_results_df['Matches'].apply(pd.Series)
    
    # Удаляем служебные колонки, созданные для мэтчинга
    cols_to_drop = ['Matches', 'trade_name_clean', 'mnn_standardized', 'mnn_match_score', 'dosage_standardized']
    final_df = pd.concat([all_results_df.drop(columns=[col for col in cols_to_drop if col in all_results_df.columns]), match_details], axis=1)
    
    # Возвращаем только требуемые колонки
    return final_df[FINAL_COLUMNS]

# --------------------------------------------------------------------
# 1.6 ФУНКЦИЯ ЭКСПОРТА В EXCEL
# --------------------------------------------------------------------
def to_excel(df):
    """Преобразование DataFrame в байты Excel для скачивания с сохранением стилей."""
    output = io.BytesIO()
    
    def highlight_matches_row(row):
        green_style = 'background-color: #C6EFCE; color: #006100;' 
        yellow_style = 'background-color: #FFEB9C; color: #9C6500;' 
        blue_style = 'background-color: #BDD7EE; color: #000000;'
        red_style = 'background-color: #FFC7CE; color: #9C0006;'
        no_style = ''

        status = row['Status']
        style = no_style

        if status == 'Полное соответствие':
            style = green_style
        elif status == 'Потенциальное соответствие':
            style = yellow_style
        elif status == 'Частичное соответствие МНН':
            style = blue_style
            
        # Агрессивное выделение: если есть переплата И статус - это какое-либо соответствие
        if (row['Potential_Saving_USD'] > 0 and 
            status in ['Полное соответствие', 'Потенциальное соответствие', 'Частичное соответствие МНН']):
            style = red_style
            return [style] * len(row)
            
        return [style] * len(row)
    
    # ПРИМЕЧАНИЕ: Перед экспортом также нужно сделать защитное преобразование типов
    # чтобы избежать ошибок форматирования при экспорте.
    cols_to_convert = [
        'Match_Score', 
        'Purchase_Price_USD', 
        'Known_Threshold_Price_USD', 
        'Client_Price_USD', 
        'Price_Difference_USD', 
        'Potential_Saving_USD',
    ]
    
    df_safe = df.copy()
    for col in cols_to_convert:
        df_safe[col] = pd.to_numeric(df_safe[col], errors='coerce').fillna(0.0)
    
    
    styled_df = df_safe.style.apply(highlight_matches_row, axis=1).format({
        'Match_Score': '{:.2f}',
        'Price_Difference_USD': '${:,.2f}',
        'Potential_Saving_USD': '${:,.2f}',
        'Purchase_Price_USD': '${:,.2f}',
        'Known_Threshold_Price_USD': '${:,.2f}',
        'Client_Price_USD': '${:,.2f}',
    })
    
    # Теперь styled_df экспортируется корректно
    styled_df.to_excel(output, index=False, engine='openpyxl')
    processed_data = output.getvalue()
    return processed_data

# ====================================================================
# 2. ФУНКЦИИ STREAMLIT и UI
# ====================================================================

def display_instructions():
    """Выводит краткую инструкцию по использованию."""
    st.header("📖 Инструкция по Использованию")
    st.markdown(f"""
    ---
    Это приложение **MatchSense** предназначено для **автоматического сопоставления** позиций из вашего **Списка Закупок** с **Эталонным Реестром** и выполнения **анализа цен**.

    ### 1. Подготовка и Загрузка Файлов (Боковая панель)
    * **Оба файла (Реестр ЛС и Заявка на закупку)** должны быть в формате **CSV** с разделителем **точкой с запятой (`;`)**.
    * **Реестр ЛС** должен содержать колонки: `mnn`, `dosage`, `known_threshold_price_USD`, `client_price_USD`, `purchase_price_USD`, `manufacturer`, `trade_name`.
    * **Заявка** должна содержать: `item_name_raw`, `quantity`.
    
    ### 2. Настройка Параметров (Боковая панель)
    * **Порог МНН:** Настройте, насколько близко название должно соответствовать МНН (рекомендуется **65-75**).
    * **Порог Дозировки:** Настройте, насколько точным должно быть совпадение дозировки для статуса "Потенциальное" (рекомендуется **80-90**).

    ### 3. Анализ Результатов
    После запуска анализа вам будет доступна **Визуализация цен**, **Таблица с деталями** сопоставления и **Кнопка для скачивания** полного отчета в Excel, включая цветовую индикацию переплат.
    """)
    st.markdown("---")


def display_price_analysis(df):
    """Выводит визуализацию и ключевые метрики анализа цен."""
    st.header("💰 Анализ Цен и Потенциальная Экономия")
    
    # Фильтруем только те строки, где есть соответствие (статус не "Не найдено")
    matched_df = df[df['Status'] != 'Не найдено'].copy()
    
    if matched_df.empty:
        st.info("Нет данных для анализа цен. Сопоставление не найдено ни для одной позиции.")
        return

    # Суммарная экономия (положительная разница = переплата)
    total_saving = matched_df['Potential_Saving_USD'].sum()
    
    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            label="Общая Разница (Переплата/Экономия)", 
            value=f"${total_saving:,.2f}", 
            delta_color="inverse", # Красный для положительного (переплата), зеленый для отрицательного (экономия)
            delta="Положительное значение указывает на переплату по сравнению с пороговой ценой."
        )

    with col2:
        # Считаем количество позиций, где была переплата (Potential_Saving_USD > 0)
        overpaid_items = matched_df[matched_df['Potential_Saving_USD'] > 0].shape[0]
        st.metric(
            label="Количество Позиций с Переплатой", 
            value=f"{overpaid_items}"
        )
    
    st.markdown("---")
    st.subheader("Визуализация: Разница в Цене по Статусу")
    
    # Гистограмма для Potential_Saving_USD по статусам
    fig_saving = px.bar(
        matched_df.groupby('Status')['Potential_Saving_USD'].sum().reset_index(),
        x='Status',
        y='Potential_Saving_USD',
        color='Status',
        title="Суммарная Потенциальная Переплата/Экономия по Статусу Мэтчинга",
        labels={'Potential_Saving_USD': 'Суммарная Разница (USD)', 'Status': 'Статус Сопоставления'}
    )
    st.plotly_chart(fig_saving, use_container_width=True)

def main():
    """Основная функция Streamlit-приложения."""
    st.set_page_config(page_title="PharmaMatch (MatchSense)", layout="wide")
    st.title("🔬 MatchSense")
    st.markdown("---")
    
    # --- ИНСТРУКЦИЯ (Показываем всегда) ---
    display_instructions()

    # --- 1. ЗАГРУЗКА ФАЙЛОВ И НАСТРОЙКИ (ПОРЯДОК ИСПРАВЛЕН) ---
    with st.sidebar:
        st.header("⚙️ Настройки и Запуск")
        
        # --- Этап 1: Загрузка Файлов ---
        st.subheader(f"Этап 1: Загрузка файлов (Разделитель: '{CSV_SEPARATOR}')")
        
        # Кодировка остается для отладки
        encoding_choice = st.selectbox(
            'Выберите кодировку CSV-файлов',
            options=['utf-8', 'cp1251', 'latin-1'],
            index=0,
            help="Если возникают ошибки кодировки, попробуйте 'cp1251' или 'latin-1'."
        )
        
        register_file = st.file_uploader(
            "1. Загрузите файл **Реестра ЛС** (CSV)", 
            type=['csv']
        )
        
        purchase_file = st.file_uploader(
            "2. Загрузите файл **Заявки на закупку** (CSV)", 
            type=['csv']
        )
        st.markdown("---")
        
        # --- Этап 2: Настраиваемые опции ---
        st.subheader("Этап 2: Настройка Парсинга и Мэтчинга")
        
        fuzzy_threshold = st.slider(
            '1. Порог соответствия дозировки',
            min_value=50, max_value=100, value=80, step=5,
            help="Процент сходства (Fuzzy Match) для дозировки."
        )
        
        mnn_score_cutoff = st.slider(
            '2. Порог соответствия МНН',
            min_value=50, max_value=100, value=65, step=5,
            help="Минимальный процент сходства (Fuzzy Match) для определения МНН."
        )
        st.markdown("---")
        
        # --- Кнопка Запуска ---
        process_button = st.button("🚀 Запустить MatchSense")
    
    # --- 2. ОБРАБОТКА ДАННЫХ ---
    if process_button:
        if register_file and purchase_file:
            # Сначала пробуем UTF-8
            try:
                # Чтение файлов с ФИКСИРОВАННЫМ разделителем и выбранной кодировкой
                register_df_raw = pd.read_csv(register_file, sep=CSV_SEPARATOR, encoding=encoding_choice)
                # Нужно сбросить указатель файла, чтобы следующий read_csv его снова прочитал
                register_file.seek(0) 
                purchase_df_raw = pd.read_csv(purchase_file, sep=CSV_SEPARATOR, encoding=encoding_choice)
                purchase_file.seek(0)
                
                
                # --- ДОБАВЛЕНА КРИТИЧЕСКАЯ ДИАГНОСТИКА (DEBUGGING) ---
                st.info(f"**🔬 Диагностика Реестра:** Обнаружено {register_df_raw.shape[0]} строк. Колонки: `{', '.join(register_df_raw.columns)}`")
                st.info(f"**🔬 Диагностика Закупки:** Обнаружено {purchase_df_raw.shape[0]} строк. Колонки: `{', '.join(purchase_df_raw.columns)}`")
                
                
                with st.spinner('Обработка и сопоставление...'):
                    final_result_df = process_matching(
                        purchase_df_raw, 
                        register_df_raw, 
                        fuzzy_threshold, 
                        mnn_score_cutoff
                    )
                
                st.session_state['final_result_df'] = final_result_df
                
                if final_result_df.empty:
                    st.warning("⚠️ Сопоставление завершено, но результат пуст. Проверьте: 1. Достаточно ли низкие пороги МНН и Дозировки. 2. Есть ли совпадения между файлами.")
                else:
                    st.success("✅ Сопоставление успешно завершено! Анализ цен и кнопка экспорта доступны ниже.")

            except Exception as e:
                # Если сработал try, то проблема, скорее всего, в кодировке/разделителе.
                error_message = f"❌ Произошла ошибка при обработке данных. Проверьте: 1. Файлы используют разделитель **точка с запятой ('{CSV_SEPARATOR}')**. 2. Выбрана верная кодировка."
                st.error(error_message)
                st.exception(e) 
        else:
            st.warning("Пожалуйста, загрузите оба файла!")

    # --- 3. ВЫВОД РЕЗУЛЬТАТОВ ---
    if 'final_result_df' in st.session_state and not st.session_state['final_result_df'].empty:
        result_df = st.session_state['final_result_df']
        
        # 3.1. Анализ Цен (Метрики и Графики)
        display_price_analysis(result_df)
        st.markdown("---")
        
        # --- ПРЕОБРАЗОВАНИЕ ТИПОВ ДЛЯ СТОЛБЦОВ С ЦЕНАМИ ---
        cols_to_convert = [
            'Match_Score', 
            'Purchase_Price_USD', 
            'Known_Threshold_Price_USD', 
            'Client_Price_USD', 
            'Price_Difference_USD', 
            'Potential_Saving_USD',
        ]
        
        for col in cols_to_convert:
            result_df[col] = pd.to_numeric(
                result_df[col], 
                errors='coerce' 
            ).fillna(0.0)      

        # 3.2. Таблица Детальных Результатов (ВОССТАНОВЛЕНО)
        st.header("📋 Детальные Результаты Сопоставления")
        st.markdown("**Цветовая индикация:** 🟢 Полное, 🟡 Потенциальное, 🔵 Частичное МНН, 🔴 Переплата")
        
        def highlight_row(row):
            status = row['Status']
            
            if row['Potential_Saving_USD'] > 0 and status != 'Не найдено':
                # Выделяем всю строку красным при переплате
                return ['background-color: #FFC7CE; color: #9C0006;'] * len(row)
            elif status == 'Полное соответствие':
                return ['background-color: #C6EFCE; color: #006100;'] * len(row)
            elif status == 'Потенциальное соответствие':
                return ['background-color: #FFEB9C; color: #9C6500;'] * len(row)
            elif status == 'Частичное соответствие МНН':
                return ['background-color: #BDD7EE; color: #000000;'] * len(row)
            else:
                return [''] * len(row)

        st.dataframe(
            result_df.style.apply(highlight_row, axis=1).format({
                'Match_Score': '{:.2f}',
                'Price_Difference_USD': '${:,.2f}',
                'Potential_Saving_USD': '${:,.2f}',
                'Purchase_Price_USD': '${:,.2f}',
                'Known_Threshold_Price_USD': '${:,.2f}',
                'Client_Price_USD': '${:,.2f}',
            }), 
            height=500,
            use_container_width=True
        )

        st.markdown("---")
        
        # Кнопка для скачивания (с сохранением стилей)
        st.download_button(
            label="📥 Скачать полный отчет (Excel)",
            data=to_excel(result_df),
            file_name="matching_results_with_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
if __name__ == '__main__':
    # Проверка на Plotly
    try:
        import plotly.express as px
    except ImportError:
        st.error("Для визуализации требуется Plotly. Выполните: pip install plotly")
        st.stop()
        
    main()
    