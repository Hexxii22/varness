# Обзор: харнессы и инструменты для генерации SVG-логотипов (октябрь 2026)

Поиск по GitHub (поиск по репозиториям, темам `svg` + `agent-skills`, MCP-серверам) и по вебу,
12.10.2026. Звёзды указаны на дату поиска. Под «харнессом» здесь понимается обвязка вокруг LLM-агента,
в которой агент сам пишет SVG, а харнесс рендерит, проверяет, показывает результат и экспортирует.

## 1. Скиллы для агентов (агент пишет SVG сам)

| Репозиторий | ★ | Что внутри | Лицензия | Оценка |
|---|---|---|---|---|
| [kaankiziltug/logo-design-skill](https://github.com/kaankiziltug/logo-design-skill) | ~2.9k | SKILL.md + 8 Python-скриптов (stdlib): `svg_audit.py` (оценка 0–100 по эвристикам XML), concept sheet в PNG, HTML-превью, экспорт вариантов и favicon, справочник принципов, библиотека из 1 400+ логотипов | MIT (кроме библиотеки) | **Лучший из найденных.** Слабые места: аудит читает только XML и не смотрит на отрендеренные пиксели (нет проверки на 16/32px, в одном цвете, в оттенках серого), нет истории итераций и откатов, нет проверки похожести концептов. В библиотеке лежат чужие товарные знаки |
| [neonwatty/logo-designer-skill](https://github.com/neonwatty/logo-designer-skill) | ~150 | Процесс «интервью → 3–5 концептов → доработка → экспорт PNG 16–2048» | MIT | Хорошо описан процесс, но автоматических проверок качества нет |
| [Claude-Booster/logo-forge](https://github.com/Claude-Booster/logo-forge) | 0 | Гейты `lf_slop.py` (клише, гигиена SVG), `lf_color.py` (палитра, рендер на 16/32px), экспорт | не указана | Идея гейтов против «AI-шаблонности» хорошая; проект новый, лицензии нет |
| [GKjohns/logo-design-skill](https://github.com/GKjohns/logo-design-skill), [qiguangyang/logo-generator-skill](https://github.com/qiguangyang/logo-generator-skill), [durmazoguzhan/svg-logo-maker](https://github.com/durmazoguzhan/svg-logo-maker), [deserteaglemj/logo-creation-skill](https://github.com/deserteaglemj/logo-creation-skill) | 0–2 | Небольшие скиллы: галерея концептов, экспорт | разные | Малоизвестные, без пиксельных проверок |
| [htuzel/gemini-svg-creator](https://github.com/htuzel/gemini-svg-creator) | 2 | Скилл, который отдаёт генерацию Gemini через MCP | — | Зависит от внешней модели и API |

## 2. MCP-серверы

| Репозиторий | ★ | Что делает | Оценка |
|---|---|---|---|
| [arikusi/nakkas](https://github.com/arikusi/nakkas) | ~28 | JSON-конфиг → SVG, возвращает модели PNG-превью, валидирует ссылки, проверяет контраст текста по WCAG, CSS/SMIL-анимации | Настоящий render-loop, но это не инструмент для логотипов: работает через свой DSL, а не через SVG |
| [mcpware/logoloom](https://github.com/mcpware/logoloom) | ~47 | `text_to_path`, `optimize_svg` (SVGO), `export_brand_kit`, `image_to_svg` (vtracer) | Хорошая обвязка экспорта, но качество не оценивает |
| [GenWaveLLC/svgmaker-mcp](https://github.com/GenWaveLLC/svgmaker-mcp) | ~88 | Обёртка над платным API SVGMaker | Нужен ключ, генерация идёт на чужом сервисе |
| QuiverAI MCP (quiver.ai) | — | Хостинговая генерация и векторизация SVG | Не open source |

## 3. Общие дизайн-харнессы

| Репозиторий | ★ | Оценка |
|---|---|---|
| [nexu-io/open-design](https://github.com/nexu-io/open-design) | ~100k | Десктоп-приложение, где кодовый агент выступает дизайн-движком (прототипы, слайды, видео). Мощное, но не заточено под логотипы и тяжёлое |
| [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design), [bybit-exchange/svg-diagram](https://github.com/bybit-exchange/svg-diagram) | 52k / 0.6k | SVG-диаграммы со своим линтером. Хорошие образцы подхода «скилл + линтер», но не про логотипы |

## 4. Модели генерации SVG (исследования, нужен GPU)

| Репозиторий | ★ | Заметка |
|---|---|---|
| [joanrod/star-vector](https://github.com/joanrod/star-vector) | ~4.6k | VLM для перевода картинки или текста в SVG. Сильнее всего в векторизации иконок |
| [OmniSVG/OmniSVG](https://github.com/OmniSVG/OmniSVG) | ~2.6k | NeurIPS 2025, сквозная генерация SVG |
| [ximinng/LLM4SVG](https://github.com/ximinng/LLM4SVG) | — | CVPR 2025 |
| [ximinng/SVGDreamer](https://github.com/ximinng/SVGDreamer), [SVGDreamerV2](https://github.com/ximinng/SVGDreamerV2) | ~450 | Text-to-SVG через диффузию. Медленно, сотни путей, для чистых логотипов не подходит |
| [kingnobro/Chat2SVG](https://github.com/kingnobro/Chat2SVG) | ~250 | CVPR 2025, LLM + диффузия |

Свежие статьи (GVR-Coder, Render-in-the-Loop, RefineSVG, IntroSVG) сходятся на одной схеме:
**сгенерировать → отрендерить → проверить → исправить**. Готового открытого инструмента, который даёт
эту схему агенту для логотипов, мы не нашли.

## 5. Векторизация и библиотеки (смежные задачи)

- Растр → SVG: [shunyagatha/Vecline](https://github.com/shunyagatha/Vecline), [botmonster/image2svg-mcp](https://github.com/botmonster/image2svg-mcp),
  [dheerajponnaganti/rasterless](https://github.com/dheerajponnaganti/rasterless) (potrace).
- Готовые логотипы брендов (не генерация): [glincker/thesvg](https://github.com/glincker/thesvg),
  [lobehub/lobe-icons](https://github.com/lobehub/lobe-icons).

## Вывод

Ни один найденный инструмент не сочетает всё, что нужно агенту для итеративной работы над логотипом:

1. **пиксельные проверки по настоящим рендерам**: исчезающие на 16/32px детали, заплывающие просветы,
   одноцветная и серая версии, фальшивые белые «дырки», оптический центр;
2. **контакт-лист одной картинкой**, который мультимодальная модель сама читает между итерациями;
3. **историю версий** с подсветкой регрессий и откатом;
4. **проверку разнообразия концептов** (не сделал ли агент пять вариаций одной идеи);
5. **обводку текста настоящим шрифтом** с кернингом (для вордмарков);
6. **экспорт продакшн-набора**: favicon.ico, PWA/Apple-иконки, моно-версии;

и всё это локально, без API-ключей. Поэтому сделан **varness**. Из найденного стоит взять идеи:
справочник и процесс из kaankiziltug/logo-design-skill, «анти-клише» гейты из logo-forge, превью для модели
из nakkas. В varness они переосмыслены так, чтобы проверки опирались на пиксели, а не на XML.
