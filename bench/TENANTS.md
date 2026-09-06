# Тенанты знаний по семьям (sLAVA, боевой сервер-1)

**Модель:** семья = коллекция Qdrant (тенант знаний). sLAVA префиксует имя → `slava_fam_<family>`.
Дефолтный `tenant_id` коллекции = имя семьи; профиль ретривера привязан per-collection.
Создано/проверено на боевой sLAVA через ssh-джамп (я → сервер-2 → сервер-1).

## 8 семейных коллекций

| Семья | Коллекция | Профиль | tenant_id | Статус |
|---|---|---|---|---|
| finance | slava_fam_finance | legal_ru | demo | ФЗ-402, 6 чанков — цепочка 5/5 (CHAIN_RESULTS) |
| analytics | slava_fam_analytics | reglament_ru | analytics | маркер-seed |
| architecture | slava_fam_architecture | reglament_ru | architecture | маркер-seed |
| management | slava_fam_management | reglament_ru | management | маркер-seed |
| research | slava_fam_research | reglament_ru | research | маркер-seed |
| engineering | slava_fam_engineering | reglament_ru | engineering | маркер-seed |
| critic | slava_fam_critic | reglament_ru | critic | маркер-seed |
| decisions | slava_fam_decisions | reglament_ru | decisions | маркер-seed |

## Проверка изоляции тенантов: ✅ 8/8 держится

Метод: в каждую семью залит маркерный документ с уникальным кодовым словом
(`<FAMILY>_MARKER_QX7`). Затем запрос по теме семьи в её коллекцию → проверка, что
в выдаче есть свой маркер и НЕТ чужих (точное совпадение по границе слова).

Результат: все 8 семей — `own=yes, foreign=none`. Ни одна семья не видит корпус другой.
Каждый запрос ограничен своей коллекцией → семейный периметр знаний соблюдён.

> Примечание: первый прогон дал ложную «протечку» research←architecture — артефакт
> подстроки (`ARCH_MARKER_QX7` ⊂ rese`ARCH_MARKER_QX7`), не sLAVA. Точный поиск по
> границе слова подтвердил чистую изоляцию.

## Профили ретривера (доработка)

Сейчас все несемейные — `reglament_ru` (дефолт). Заложенная per-family дифференциация:
finance/engineering → BM25-гибрид (точные коды/артикулы/статьи), research/analytics →
семантика. Требует создания профилей в `profiles/` sLAVA (сейчас доступны legal_ru/
reglament_ru/support_ru) — отдельная доработка, на изоляцию не влияет.

## Дальше

- Наполнить семьи реальными доменными корпусами (сейчас finance = ФЗ-402, остальные = маркеры).
- Профили per-family (гибрид/семантика).
- На боксе: та же схема на локальной sLAVA (embed/rerank в периметре), без джампа.

Связь: `bench/CHAIN_RESULTS.md` (связка e2e), `docs/ABOP_RUNTIME_ARCHITECTURE.md` (RAG на sLAVA).
