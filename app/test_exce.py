import pandas as pd
from sqlalchemy import create_engine, inspect
from app.db.session import engine

OUTPUT_FILE = "db_export.xlsx"

def export_all_tables_to_excel():
    insp = inspect(engine)
    table_names = insp.get_table_names()

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for table in table_names:
            try:
                df = pd.read_sql_table(table, engine)
                df.to_excel(writer, sheet_name=table[:31], index=False)  
                print(f"Таблица {table} выгружена ({len(df)} строк).")
            except Exception as e:
                print(f"Ошибка при экспорте {table}: {e}")

    print(f"\n✅ Экспорт завершён! Файл сохранён: {OUTPUT_FILE}")


if __name__ == "__main__":
    export_all_tables_to_excel()
