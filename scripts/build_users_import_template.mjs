import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const templatePath = "app/static/users_template.xlsx";
const outputDir = "outputs/import_template";
const previewDir = `${outputDir}/preview`;
await fs.mkdir(previewDir, { recursive: true });

// Обязательная проверка текущего шаблона перед изменением.
try {
  const oldBook = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
  const overview = await oldBook.inspect({ kind: "workbook,sheet,table", maxChars: 4000, tableMaxRows: 5, tableMaxCols: 12 });
  console.log("OLD_TEMPLATE\n" + overview.ndjson);
  const oldPreview = await oldBook.render({ sheetName: "Пользователи", range: "A1:J6", scale: 1.2, format: "png" });
  await fs.writeFile(`${previewDir}/before.png`, new Uint8Array(await oldPreview.arrayBuffer()));
} catch (error) {
  console.log(`OLD_TEMPLATE_UNAVAILABLE: ${error.message}`);
}

const workbook = Workbook.create();
const users = workbook.worksheets.add("Пользователи");
const groups = workbook.worksheets.add("Группы");
const subdivisions = workbook.worksheets.add("Подразделения");
const rooms = workbook.worksheets.add("Аудитории");
const subjects = workbook.worksheets.add("Дисциплины");
const help = workbook.worksheets.add("Инструкция");

function setupInputSheet(sheet, range, widths) {
  const header = sheet.getRange(range.split(":")[0].replace(/\d+$/, "1") + ":" + range.split(":")[1].replace(/\d+$/, "1"));
  header.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  header.format.rowHeight = 34;
  sheet.getRange(range).format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  widths.forEach(([column, width]) => { sheet.getRange(`${column}1:${column}4`).format.columnWidth = width; });
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
}

users.getRange("A1:K4").values = [
  ["ФИО", "Электронная почта", "Роль", "Телефон", "Дата рождения", "Группа", "Подразделение", "Предмет", "Номер зачётки", "Год поступления", "Курс"],
  ["", "", "", "", null, "", "", "", "", "", ""],
  ["", "", "", "", null, "", "", "", "", "", ""],
  ["", "", "", "", null, "", "", "", "", "", ""],
];
setupInputSheet(users, "A1:K4", [["A",28],["B",28],["C",18],["D",20],["E",18],["F",18],["G",22],["H",20],["I",20],["J",18],["K",12]]);
users.getRange("E2:E200").format.numberFormat = "yyyy-mm-dd";
users.getRange("C2:C200").dataValidation = { rule: { type: "list", values: ["студент", "преподаватель", "директор", "администратор"] } };

groups.getRange("A1:B4").values = [
  ["Код группы", "Название группы"], ["", ""], ["", ""], ["", ""],
];
setupInputSheet(groups, "A1:B4", [["A",18],["B",42]]);

subdivisions.getRange("A1:D4").values = [
  ["Код подразделения", "Название подразделения", "Тип подразделения", "Код родительского подразделения"],
  ["", "", "", ""], ["", "", "", ""], ["", "", "", ""],
];
setupInputSheet(subdivisions, "A1:D4", [["A",22],["B",38],["C",24],["D",34]]);

rooms.getRange("A1:C4").values = [
  ["Код аудитории", "Название аудитории", "Вместимость"],
  ["", "", null], ["", "", null], ["", "", null],
];
setupInputSheet(rooms, "A1:C4", [["A",20],["B",36],["C",18]]);
rooms.getRange("C2:C200").dataValidation = { rule: { type: "whole", operator: "between", formula1: 1, formula2: 10000 } };
rooms.getRange("C2:C200").format.numberFormat = "0";

subjects.getRange("A1:E4").values = [
  ["Код дисциплины", "Название дисциплины", "Тип дисциплины", "Email основного преподавателя", "Email преподавателей"],
  ["", "", "", "", ""], ["", "", "", "", ""], ["", "", "", "", ""],
];
setupInputSheet(subjects, "A1:E4", [["A",20],["B",38],["C",24],["D",32],["E",42]]);

help.getRange("A1:D1").merge();
help.getRange("A1:D1").values = [["Массовый импорт данных"]];
help.getRange("A1:D1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  rowHeight: 32,
  horizontalAlignment: "center",
};
help.getRange("A3:B13").values = [
  ["Порядок", "Что заполнять"],
  [1, "Подразделения: название обязательно; родитель указывается кодом. Строки могут идти в любом порядке."],
  [2, "Группы: код обязателен, название необязательно."],
  [3, "Пользователи: обязательны ФИО, почта и роль. Студенту нужна группа, преподавателю можно указать подразделение."],
  [4, "Аудитории: код обязателен, вместимость — положительное целое число."],
  [5, "Дисциплины: название обязательно. Тип создаётся автоматически, если его ещё нет."],
  [6, "Основной преподаватель и остальные преподаватели указываются по email уже существующих или импортируемых пользователей."],
  [7, "Несколько email преподавателей разделяйте запятой или точкой с запятой."],
  [8, "Можно оставить ненужные листы пустыми и импортировать только один справочник."],
  [9, "Не меняйте названия листов и заголовки колонок."],
  [10, "После импорта сохраните итоговый Excel-отчёт: в нём будут статусы, ошибки и пароли новых пользователей."],
];
help.getRange("A3:B3").format = { fill: "#D9EAF7", font: { bold: true, color: "#17365D" } };
help.getRange("A3:B13").format.wrapText = true;
help.getRange("A3:B13").format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
help.getRange("A3:B13").format.rowHeight = 38;
help.getRange("A1:A13").format.columnWidth = 14;
help.getRange("B1:B13").format.columnWidth = 82;
help.showGridLines = false;

const overview = await workbook.inspect({ kind: "workbook,sheet,table", maxChars: 6000, tableMaxRows: 5, tableMaxCols: 12 });
console.log("NEW_TEMPLATE\n" + overview.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log("ERROR_SCAN\n" + errors.ndjson);

const previews = [
  ["Пользователи", "A1:K6", "users"], ["Группы", "A1:B5", "groups"],
  ["Подразделения", "A1:D5", "subdivisions"], ["Аудитории", "A1:C5", "rooms"],
  ["Дисциплины", "A1:E5", "subjects"], ["Инструкция", "A1:D13", "help"],
];
for (const [sheetName, range, fileName] of previews) {
  const preview = await workbook.render({ sheetName, range, scale: 1.4, format: "png" });
  await fs.writeFile(`${previewDir}/${fileName}.png`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/users_template.xlsx`);
await fs.copyFile(`${outputDir}/users_template.xlsx`, templatePath);
console.log(`SAVED ${templatePath}`);
