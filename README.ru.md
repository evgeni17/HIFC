# HIFC — импорт и экспорт IFC для Houdini

HIFC добавляет в SideFX Houdini две SOP-ноды для импорта и экспорта IFC. Плагин работает на
[IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell), том же движке, что стоит за аддоном Bonsai для Blender.
Blender не нужен.

* **HIFC IFC Import** читает IFC2X3, IFC4 и IFC4X3. Повторяющаяся геометрия хранится один раз и расставляется
  packed-копиями по матрицам из IFC; при необходимости — packed-примитив на каждый элемент или обычные полигоны.
  Атрибуты: `path`, GUID, класс, этаж, материал, цвет и все наборы свойств.
* **HIFC IFC Export** записывает полигоны в IFC. Структура BIM (иерархия, классы, этажи, материалы, свойства)
  задаётся атрибутами примитивов. GlobalId не меняются между экспортами.
* **Check Attributes** проверяет атрибуты перед экспортом. **Шаблон атрибутов** (Primitive Wrangle)
  и встроенная **справка** (F1 на ноде экспорта) объясняют, как собрать правильную BIM-структуру.

## Установка

1. Склонируйте репозиторий (`git clone https://github.com/evgeni17/HIFC.git`), например в `~/houdini_tools/HIFC`.
2. Скопируйте `HIFC.json` в папку packages Houdini и пропишите в `"HIFC"` путь к папке плагина.
   Для русской справки поставьте `"HIFC_HELP_LANG": "ru"`.
3. Запустите Houdini и выполните **HIFC › Install / Update ifcopenshell**
   (или установите вручную, см. `vendor/README.md`), затем перезапустите Houdini.
4. После смены языка справки один раз выполните **HIFC › Rebuild HDAs**.

## Скорость

* **Output: Auto** (по умолчанию) — повторяющаяся геометрия (одинаковые окна, двери, мебель) кладётся в память
  один раз, остальное остаётся полигонами: упаковывать всё подряд смысла нет — это утяжеляет вьюпорт.
* На выходе импорта есть группы примитивов `ifc_packed` и `ifc_polygons` — инстансы отделяются от
  остальной модели одним Blast.
* **Disk Cache** — повторное открытие того же файла занимает около секунды, в том числе в новой сессии.
* **Property Sets** — читайте только нужные наборы (`Pset_* Qto_*`, `* ^ArchiCADProperties`): свойства медленнее всего.
* Замеры на своих файлах: `hython tests/perf_bench.py model.ifc report.json`.

## Свойства

Переносятся одиночные, перечислимые и списочные значения, диапазоны и величины `IfcElementQuantity`.
`IfcComplexProperty` разворачивается в `Родитель.Потомок`. Табличные и ссылочные свойства не переносятся —
нода сообщает о них предупреждением и пишет его в детальный атрибут `ifc_warnings`.

## Тестирование

Тестовые файлы — официальные [Certification datasets](https://github.com/buildingSMART/Certification-datasets)
от buildingSMART (CC BY 4.0): `python tests/fetch_datasets.py`, затем `python tests/roundtrip.py`.

## Лицензия

© 2026 EOK. [Apache License 2.0](LICENSE). Сторонние компоненты перечислены в [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
IfcOpenShell (LGPL-3.0+) в репозиторий не входит и ставится отдельно.
HIFC — независимый проект, не связанный с SideFX, buildingSMART, IfcOpenShell и Bonsai.
