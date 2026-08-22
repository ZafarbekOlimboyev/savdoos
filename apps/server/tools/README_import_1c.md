# 1С → SavdoOS import konvertori (`import_1c.py`)

Do'kon 1С'dan chiqargan `.xls/.xlsx` fayllarni SavdoOS mahsulot-import formatiga
(`/products/import/commit`) aylantiradi. Ustunlarni **avtomatik aniqlaydi** (kirill/uzbek
sarlavhalar), bir nechta faylni **barkod yoki nom bo'yicha ulaydi**.

## Talab
```
pip install pandas xlrd openpyxl
```

## Ustunlar avtomatik topiladi
Sarlavhadan kalit so'zlar bo'yicha (butun so'z sifatida, `штрихкода` ichidagi `код` mos kelmaydi):
- **name** ← Наименование / Номенклатура / Название / Товар / **Владелец** / Nomi
- **barcode** ← Штрихкод / EAN
- **article** ← Артикул / Код товара / SKU
- **sell** ← Розничная цена / Цена продажи / Цена
- **buy** ← Цена закупки / Закупочная / Себестоимость
- **stock** ← Остаток / Количество / Кол-во
- **category** ← Категория / Группа

Xato aniqlasa — qo'lda ko'rsating: `--map name=Владелец,barcode=Штрихкод,sell=Цена`

## Misollar
```bash
# 1) Ko'rib chiqish (ustun-xaritasi + birinchi 8 qator, hech narsa yuklamaydi)
python tools/import_1c.py "katalog.xls" --preview

# 2) Bir nechta faylni ulab JSON chiqarish (katalog + narx + qoldiq alohida bo'lsa ham)
python tools/import_1c.py "katalog.xls" "narxlar.xls" "qoldiq.xls" -o rows.json

# 3) To'g'ridan-to'g'ri serverga yuklash (1000 tadan bo'lib)
python tools/import_1c.py "katalog.xls" "narxlar.xls" "qoldiq.xls" \
   --post --phone +998901234567 --password savdo1234
```

## Ulash (join) kaliti
Har faylда shu ustunlardan biri bo'lsa, fayllar avtomatik birlashadi (prioritet shu tartibda):
**barkod → artikul → nom**. Ya'ni narx/qoldiq faylida barkod bo'lsa — eng ishonchli ulanadi.

## Eslatma
- Faqat katalog berilsa — natijaда narx/qoldiq bo'lmaydi (script ogohlantiradi). Sotish uchun
  **Прайс-лист**, ombor uchun **Остатки товаров** fayllari ham kerak.
- Chiqish faqat UTF-8 (kirill saqlanadi). PowerShell `Get-Content` ANSI o'qib buzib ko'rsatishi mumkin — fayl aslida to'g'ri.
