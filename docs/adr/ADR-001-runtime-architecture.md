# ADR-001: Runtime-архитектура desktop-приложения

- **Статус:** Accepted for MVP
- **Дата:** 2026-07-18
- **Решение:** Python 3.12 + PySide6 + PyInstaller `onedir`/platform app bundle
- **Пересмотр:** после стабильного headless pipeline и измерений packaged MVP

## 1. Контекст

Нужно доставить отдельное локальное desktop-приложение для Windows и macOS. Пользователь не устанавливает Python, FFmpeg, библиотеки или STT-модель вручную. Самые высокие продуктовые риски находятся не в shell/UI, а в следующих областях:

- границы слов и недопустимость word clipping;
- качество script-to-ASR alignment;
- sample-exact edit map и согласованность всех артефактов;
- локальный STT и packaged sidecars;
- self-contained Windows/macOS-сборки.

Предыдущий `PROPOSED_ARCHITECTURE.md` рекомендовал Tauri/Rust, но это предложение не является уже принятым решением. Текущий критерий выбора для MVP:

> минимальный технический риск и максимально быстрая доставка работающего продукта при сохранении возможности будущей миграции.

Сравниваются:

- **A. Python 3.12 + PySide6 + PyInstaller**;
- **B. Rust/Tauri core с локальными sidecar-процессами**.

Оба варианта обязаны использовать один и тот же продуктовый контракт: local-only processing, immutable original script, integer-sample timebase, versioned JSON artifacts, bundled FFmpeg/STT и отсутствие серверной инфраструктуры.

## 2. Decision drivers

В порядке приоритета MVP:

1. скорость получения тестируемого end-to-end результата;
2. риск ошибки в audio/alignment/edit-map pipeline;
3. простота диагностики packaged приложения на двух OS;
4. возможность тестировать domain-логику без GUI и sidecars;
5. self-contained локальная поставка;
6. повторное использование Python-знаний, идей и fixtures reference-проекта без переноса Django;
7. управляемость лицензий и native payload;
8. размер и холодный старт;
9. долгосрочная поддерживаемость и путь миграции.

Размер shell/runtime имеет меньший вес, чем STT-модель и FFmpeg payload. «Меньший executable» сам по себе не компенсирует более медленную и рискованную реализацию core pipeline.

## 3. Общая архитектура, обязательная для обоих вариантов

```text
Desktop UI
  -> Application service / job orchestrator
    -> dependency-light domain contracts and algorithms
      -> Audio/STT/filesystem ports
        -> bundled ffmpeg + ffprobe + local STT executable/library
    -> versioned JSON/WAV/SRT artifact adapters
```

Независимо от языка:

- GUI не содержит processing logic;
- domain не импортирует GUI, subprocess или editor-specific exporters;
- canonical time - integer audio samples, intervals `[start,end)`;
- FFmpeg/STT вызываются по абсолютным bundled paths;
- sidecar protocol machine-readable и versioned;
- `edit_map.json`, `subtitle_blocks.json`, report и manifest имеют JSON schemas;
- staging/validation/atomic publish обязательны;
- Premiere/Resolve и direct CapCut Draft не входят в MVP runtime decision.

## 4. Вариант A - Python 3.12 + PySide6 + PyInstaller

### 4.1 Предлагаемая форма

```text
PySide6 Widgets UI
  -> Python application service
    -> pure Python domain modules
    -> subprocess adapters
       -> ffmpeg / ffprobe
       -> whisper.cpp-based local STT wrapper
    -> WAV/SRT/JSON artifact store
```

Сборка выполняется отдельно на Windows и macOS. Для MVP используется PyInstaller `onedir` на Windows и обычный `.app` bundle/onedir-like layout на macOS, а не self-extracting `onefile`.

PyInstaller включает интерпретатор и зависимости, поэтому пользователю не нужен установленный Python. Его документация подчёркивает, что one-folder проще диагностировать, а one-file распаковывает зависимости во временный каталог и стартует медленнее ([PyInstaller operating mode](https://www.pyinstaller.org/en/stable/operating-mode.html)). Qt for Python официально описывает PyInstaller как вариант cross-platform deployment для PySide6 ([Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)).

### 4.2 Оценка

| Критерий | Оценка | Обоснование |
|---|---:|---|
| Скорость разработки | Высокая | Один основной язык для UI, orchestration, algorithms и serializers; короткий цикл запуска тестов. |
| Сложность для текущего проекта | Низкая/средняя | Reference и планирование уже на Python; команда может отделить чистые идеи/fixtures без переноса Django. |
| Локальный STT | Хорошо | whisper.cpp остаётся отдельным process adapter; Python не обязан включать PyTorch. |
| FFmpeg | Хорошо | Прямой typed subprocess adapter; тот же executable потребуется и варианту B. |
| Упаковка Windows/macOS | Средне | Поддерживается, но требует platform-native builds, hooks, Qt plugins, resource layout и nested signing tests. |
| Размер приложения | Хуже B | В bundle входят CPython и Qt; однако STT model, вероятно, доминирует в общем размере. |
| Отладка | Высокая | Python stack traces, быстрые unit tests; `onedir` позволяет видеть собранные файлы. |
| Тестирование | Высокая | Mature unit/property/golden tooling; простые fake ports; алгоритмы легко тестируются без GUI. |
| Переиспользование Python backend | Максимальное по идеям/fixtures | Возможен контролируемый перенос тестовых случаев и независимая реализация pure logic; SaaS dependencies не нужны. |
| Долгосрочная поддержка | Средняя | Нужно управлять CPython/Qt/PyInstaller pinning и переходами Python minor; GIL не мешает sidecar-heavy pipeline, но CPU-heavy Python может потребовать Rust/native модуль. |
| Риск MVP | Ниже | Главный риск - packaging quirks, а не новая реализация pipeline на незнакомом стеке. |

### 4.3 Преимущества

- Самый короткий путь к headless fake-adapter slice, затем к реальному WAV/STT pipeline.
- PySide6 даёт native desktop widgets без web frontend и WebView compatibility layer.
- Python удобен для Unicode alignment, dynamic programming, JSON schemas, audio test fixtures и быстрой калибровки.
- FFmpeg и whisper.cpp изолированы как процессы; падение/обновление модели не требует связывать C/C++ ABI с GUI.
- Чистые domain contracts и JSON protocols позволяют позже заменить отдельный модуль Rust-реализацией.

### 4.4 Недостатки и риски

- Bundle больше; холодный старт и antivirus false positives нужно измерить.
- PyInstaller static analysis может пропустить динамические imports/resources; нужны explicit spec/hooks и packaged contract tests.
- Qt plugins и native libraries усложняют signing/notarization.
- PyInstaller build platform-specific; нельзя считать одну macOS-сборку доказательством Windows.
- Python 3.12 в июле 2026 находится в security-only фазе с плановым EOL в октябре 2028 ([Python version status](https://devguide.python.org/versions/)). Для MVP это допустимый фиксированный baseline, но до публичного GA должен быть утверждён план обновления minor runtime; архитектура не должна использовать 3.12-only особенности без необходимости.
- PySide6 доступен под LGPLv3/GPLv3 или commercial license; выбранный compliance path и допустимые Qt modules должны быть утверждены до dependency addition ([Qt for Python](https://doc.qt.io/qtforpython-6/)).
- GIL ограничивает CPU-bound Python threads. Здесь STT и FFmpeg работают вне процесса; если alignment/pause analysis станет bottleneck, он выносится в worker process или Rust/native component после профилирования.

### 4.5 Меры снижения риска

- `onedir`, не `onefile`, для MVP.
- Только Qt Widgets/Essentials, без QtWebEngine/QML, если UX не требует их.
- Pinned lock + explicit PyInstaller spec; inventory bundle contents.
- Platform-native CI/clean-machine tests с пустым `PATH`.
- FFmpeg/STT sidecars с versioned JSON protocol и owned process tree.
- Domain modules без imports PySide6/subprocess.
- Packaging spike до полноценного GUI: окно + sidecar probe + Unicode path + signing dry run.
- Отдельный ADR для Python minor upgrade до первой долгоживущей публичной ветки.

## 5. Вариант B - Rust/Tauri core с локальными sidecars

### 5.1 Предлагаемая форма

```text
Tauri webview UI
  -> Tauri commands
    -> Rust application/domain core
    -> Rust process/runtime adapters
       -> ffmpeg / ffprobe
       -> whisper.cpp wrapper
    -> WAV/SRT/JSON artifact store
```

Tauri официально поддерживает target-specific external binaries/sidecars, включая executables, созданные на любом языке ([Tauri sidecars](https://v2.tauri.app/develop/sidecar/)). На Windows Tauri использует WebView2, на macOS - системный WKWebView ([Tauri prerequisites](https://v2.tauri.app/start/prerequisites/), [Tauri webview versions](https://v2.tauri.app/reference/webview-versions/)).

### 5.2 Оценка

| Критерий | Оценка | Обоснование |
|---|---:|---|
| Скорость разработки | Низкая/средняя для MVP | Нужно одновременно создать Rust core, Tauri bridge и web UI, а также освоить platform packaging. |
| Сложность для текущего проекта | Выше A | Новый язык/toolchain и межслойные contracts появляются до проверки продуктового pipeline. |
| Локальный STT | Хорошо | Sidecar pattern официальный; возможна будущая in-process интеграция, но ABI/GPU complexity возрастает. |
| FFmpeg | Хорошо | Typed process handling удобно, но не даёт существенного MVP-преимущества перед Python adapter. |
| Упаковка Windows/macOS | Средне/хорошо | Tauri имеет bundling/sidecar conventions, но target binaries, WebView2, signing и notarization всё равно требуют отдельных тестов. |
| Размер приложения | Лучше A | Rust shell/core обычно меньше CPython+Qt; model/FFmpeg payload остаётся тем же. |
| Отладка | Средняя | Сильная диагностика Rust, но ошибки могут пересекать webview/IPC/Rust/sidecar layers. |
| Тестирование | Хорошая | Rust unit/property tests сильны; UI/IPC и перенос Python fixtures требуют дополнительной работы. |
| Переиспользование Python backend | Низкое по коду, среднее по идеям | Fixtures и behaviour полезны, но алгоритмы/serializers переписываются. |
| Долгосрочная поддержка | Высокая потенциально | Strong types, predictable native runtime и performance; меньше bundled runtime, но Rust/Tauri/webview ecosystem надо поддерживать. |
| Риск MVP | Выше A | Самые рискованные domain-функции разрабатываются одновременно с новым runtime/UI stack. |

### 5.3 Преимущества

- Компактный native core, строгие типы и хорошая память/process safety.
- Удобная долгосрочная основа для sample arithmetic, process supervision и high-performance signal work.
- Официальная модель target-specific sidecars и permissions.
- Tauri лицензируется под MIT/Apache-2.0 where applicable ([Tauri repository](https://github.com/tauri-apps/tauri)).
- Возможность со временем уменьшить число sidecar-процессов через native libraries.

### 5.4 Недостатки и риски

- Два/три стека (Rust + web frontend + sidecars) до получения пользовательской ценности.
- Переписывание всех Python-oriented test harnesses/algorithms и более длинный цикл экспериментов alignment/chunking.
- WebView2/WKWebView добавляют platform differences и фоновое поведение, которое нужно отделять в privacy tests.
- Sidecar support не устраняет target-specific binary builds, signatures, model payload и process cancellation.
- Ошибки распределяются между frontend IPC, Rust commands и sidecar protocol.
- Риск потратить MVP-время на permissions, bundling и UI bridge вместо измерения word safety.

### 5.5 Когда вариант B становится предпочтительнее

- Python packaged prototype не проходит измеримые startup/RSS/AV/reliability budgets.
- Alignment/signal processing действительно CPU-bound после профилирования и worker/native extension недостаточны.
- Требуется сложный process supervisor или security boundary, который дешевле поддерживать в Rust.
- Продуктовая команда уже устойчиво владеет Rust/Tauri и web UI, а не осваивает их в критическом пути.
- Долгосрочный UX требует webview-экосистемы и частых UI-итераций больше, чем native Widgets.

## 6. Сводное сравнение

Шкала: 1 - плохо для текущего критерия, 5 - хорошо. Вес отражает MVP-критерий, а не универсальную оценку технологий.

| Критерий | Вес | A: Python/PySide6 | B: Rust/Tauri |
|---|---:|---:|---:|
| Скорость доставки | 5 | 5 | 2 |
| Технический риск текущей команды/проекта | 5 | 4 | 2 |
| Итерации audio/alignment logic | 5 | 5 | 3 |
| Тестируемость core | 4 | 5 | 4 |
| Локальный STT/FFmpeg | 4 | 4 | 4 |
| Cross-platform packaging | 4 | 3 | 4 |
| Диагностика packaged build | 3 | 4 | 3 |
| Переиспользование идей/fixtures | 3 | 5 | 3 |
| Размер/startup | 2 | 2 | 5 |
| Долгосрочная native maintainability | 3 | 3 | 5 |
| Сохранение пути миграции | 4 | 4 при строгих границах | 5 |

Итог по приоритетам MVP: вариант A выигрывает за счёт времени и меньшего числа одновременных неизвестных. Вариант B имеет лучший потенциальный long-term runtime, но его преимущества не снижают ключевой ранний риск - качество и безопасность самого pipeline.

## 7. Решение для MVP

Принять **вариант A: Python 3.12 + PySide6 + PyInstaller**.

Конкретизация:

1. MVP shell - PySide6 Widgets; processing logic отсутствует в GUI.
2. Core/application modules - Python с dependency-light domain layer.
3. Packaging - PyInstaller `onedir`/`.app` bundle, отдельная нативная сборка для Windows x64 и каждой обещанной macOS architecture.
4. FFmpeg/ffprobe - pinned bundled executables, вызываемые через typed subprocess adapter.
5. Local STT - pinned whisper.cpp-based executable/wrapper с versioned machine-readable protocol. `whisper.cpp` распространяется под MIT license ([whisper.cpp license](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE)).
6. Никакого system Python, system FFmpeg, `PATH` lookup, local HTTP server или cloud API.
7. Baseline model и supported languages выбираются benchmark, а не этим ADR.
8. `edit_map.json`/subtitle/report contracts проектируются независимо от Python classes и пригодны для другой реализации.

Это решение не разрешает немедленно добавлять зависимости. До добавления Python/PySide6/PyInstaller/FFmpeg/STT components требуются отдельные dependency records, license check и packaging spike.

## 8. Лицензии и влияние на упаковку

Предварительный inventory, подлежащий отдельному утверждению:

| Компонент | Назначение | Лицензия/статус | Влияние на packaging |
|---|---|---|---|
| CPython 3.12 | Runtime приложения | PSF License; 3.12 security-only до планового EOL 2028-10 | Интерпретатор включается в bundle; нужен minor-upgrade plan. |
| PySide6/Qt | Desktop UI | LGPLv3/GPLv3 или commercial; набор модулей надо аудировать | Qt libraries/plugins увеличивают bundle и требуют license notices/signing. |
| PyInstaller | Freezing | GPLv2 с exception для распространения bundled apps; проверить точный shipped version | Platform-native build, spec/hooks, bootloader, AV/signing tests. |
| FFmpeg/ffprobe | Probe/decode/render | LGPLv2.1+ по умолчанию; GPL применяется при включении GPL parts | Нужны pinned configure flags, source/build recipe и notices. Официальный checklist требует исключить `--enable-gpl`/`--enable-nonfree` для LGPL profile ([FFmpeg legal](https://ffmpeg.org/legal.html)). |
| whisper.cpp wrapper | Локальный STT | MIT для whisper.cpp; лицензия конкретной модели проверяется отдельно | Native binary на каждый target, model payload, hashes, signature и cancellation tests. |
| STT model | Word timings | Зависит от выбранного model artifact | Основной вклад в размер; provenance/license и offline delivery обязательны. |

Юридическая таблица не является legal advice. Перед публичной поставкой требуется формальная compliance review.

## 9. Архитектура после MVP

Миграция не является обязательным обещанием. После стабильного MVP выполняется измерение cold start, RSS, RTF, crash/cancel recovery, installer size, AV/signing friction и стоимости сопровождения.

Порядок возможного развития:

1. **Остаться на Python**, если бюджеты выполнены. Это предпочтительнее миграции без измеримой пользы.
2. **Вынести узкие hot paths в Rust** как native extension или отдельный versioned CLI: sample mapper, alignment DP, signal analysis или process supervisor. PySide6 UI и Python orchestration остаются.
3. **Перенести application/domain core в Rust**, сохранив JSON/fixture contracts и PySide6 shell как временный клиент.
4. **Перейти на Tauri shell** только если web UI/size/update/security requirements оправдывают дополнительный stack. Rust core и sidecars могут быть переиспользованы.

Наиболее вероятная post-MVP архитектура при наличии bottleneck:

```text
PySide6 UI or future Tauri UI
  -> stable application contract
    -> Rust core/CLI for measured critical paths
    -> unchanged ffmpeg/STT sidecars
    -> unchanged versioned artifact schemas
```

Такой подход сохраняет возможность миграции, но не заставляет MVP платить её стоимость заранее.

## 10. Последствия решения

### Положительные

- Быстрее достигается проверяемый core pipeline.
- Меньше одновременно новых инструментов и границ отказа.
- Reference fixtures и Python-oriented эксперименты легче использовать без копирования SaaS-кода.
- GUI может появиться после headless slice без смены языка.
- Migration seam существует через ports, subprocess protocols и versioned artifacts.

### Отрицательные

- Более крупный bundle и потенциально более высокий RSS/startup.
- PyInstaller/Qt resource discovery и platform signing требуют раннего spike.
- Python 3.12 имеет ограниченный support horizon; обновление minor runtime надо запланировать до EOL.
- При плохой дисциплине GUI/process imports могут проникнуть в domain; architecture tests обязательны.

### Нейтральные

- FFmpeg, STT model, signing/notarization и clean-room tests нужны в обоих вариантах.
- Выбор Python не означает перенос Django/Celery/storage/database.
- Выбор Python не означает использование cloud OpenAI/Anthropic/Gemini API.
- Выбор Python не добавляет SQLite и model manager в MVP.

## 11. Проверки, способные отменить решение

ADR пересматривается, если timeboxed packaging spike показывает хотя бы одно из следующего без приемлемой mitigation:

- PyInstaller/PySide6 не может создать self-contained bundle на обязательном target;
- nested signing/notarization стабильно не проходит;
- packaged cold start/RSS/size превышает утверждённый budget, причём STT model не является основным источником;
- antivirus/SmartScreen делает consumer delivery неприемлемой;
- required local STT adapter невозможно надёжно контролировать/cancel из Python;
- критический algorithm benchmark не достигает RTF/latency budget и процесс/Rust extension не решает проблему.

Пересмотр требует измерений на одном и том же vertical slice. Он не должен основываться только на эстетическом предпочтении языка или прежней рекомендации.

## 12. Не решено этим ADR

- baseline STT model, supported languages и quality thresholds;
- canonical WAV profile;
- численные pause/alignment/subtitle policies;
- минимальные OS/hardware;
- точный installer format и signing identities;
- Qt LGPLv3 compliance vs commercial license;
- FFmpeg build recipe и codec set;
- model delivery/size budget;
- будущий updater;
- XML/CapCut Draft/NLE compatibility.

