# tests/reference

`hifc_6_0_reference.hip.json` — снимок состояния эталонной сцены на момент выпуска 0.6.0: по каждой версии
ассетов и каждому режиму вывода параметры, число примитивов и точек, габариты, группы, атрибуты, GUID,
наборы свойств и счётчики экспорта.

Сама сцена (`.hip`) и файлы IFC в git не хранятся — их восстанавливает тест:

```bash
hython tests/hip_compat.py build  tests/reference/hifc_6_0_reference.hip
hython tests/hip_compat.py reopen tests/reference/hifc_6_0_reference.hip
```

После обновления плагина сцена должна открываться и считаться так же: расхождение со снимком — это ошибка.
