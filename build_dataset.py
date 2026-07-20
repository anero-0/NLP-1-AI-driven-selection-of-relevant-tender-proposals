import os
import glob
import re
import pandas as pd

RAW_DIR = "Выборки за месяц"
REGISTRY_DIR = "Выборки с отобранными тендерами"
OUTPUT_CSV = "dataset.csv"

def load_excel_files(directory):
    files = glob.glob(os.path.join(directory, "*.xlsx"))
    if not files:
        return pd.DataFrame()

    df_list = []
    for file in files:
        date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', file)
        file_date = date_match.group(1) if date_match else "unknown"

        try:
            df = pd.read_excel(file, header=1, engine='openpyxl')
            df = df.dropna(subset=['Номер'])
            df['source_date'] = file_date
            df_list.append(df)
        except Exception as e:
            print(f"Ошибка при чтении файла {file}: {e}")

    if not df_list:
        return pd.DataFrame()

    full_df = pd.concat(df_list, ignore_index=True)
    return full_df


def get_registry_numbers(directory):
    files = glob.glob(os.path.join(directory, "*.xlsx"))
    registry_numbers = set()

    for file in files:
        try:
            df = pd.read_excel(file, header=1, engine='openpyxl')
            df = df.dropna(subset=['Номер'])
            numbers = df['Номер'].astype(str).str.strip().tolist()
            registry_numbers.update(numbers)
        except Exception as e:
            print(f"Ошибка при чтении реестра {file}: {e}")

    return registry_numbers


def main():
    print("Начинаю сборку датасета...")

    print(f"Читаю файлы из папки '{RAW_DIR}'...")
    df = load_excel_files(RAW_DIR)

    if df.empty:
        print("Папка пуста или файлы не найдены. Проверь путь.")
        return

    df = df.sort_values(by='source_date')
    df = df.drop_duplicates(subset=['Номер'], keep='last')
    unique_count = len(df)

    if os.path.exists(REGISTRY_DIR):
        print(f"Папка '{REGISTRY_DIR}' найдена. Сопоставляю с реестром...")
        reg_numbers = get_registry_numbers(REGISTRY_DIR)
        df['in_registry'] = df['Номер'].astype(str).str.strip().isin(reg_numbers)
    else:
        print(f"Папка '{REGISTRY_DIR}' пока не создана. Колонка in_registry заполнена False.")
        df['in_registry'] = False

    df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    print("\n" + "=" * 50 + "\n")
    print(f"Датасет обновлён, строк {unique_count}")

if __name__ == "__main__":
    main()