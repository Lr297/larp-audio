# Deterministic pause detection

## Scope

Этап находит интервалы сигналов, которые FFmpeg классифицирует как тишину, внутри уже канонического WAV: mono, 48 000 Hz, PCM s16le. Результат — только упорядоченный список `PauseSegment`. Компонент не изменяет WAV, не принимает решение об удалении, не строит `edit_map.json` и не использует STT или alignment.

Pipeline-интерфейс принимает существующий `AudioInfo`, чтобы не создавать второй источник metadata. Техническая CLI читает только точный WAV header стандартным модулем `wave` и создаёт тот же `AudioInfo`; она отклоняет неканонический вход.

## Algorithm choice

Используется FFmpeg filter `silencedetect` с null output:

```text
ffmpeg -i INPUT -map 0:STREAM -af silencedetect=noise=THRESHOLDdB:d=DURATION -f null -
```

Выбор сделан по следующим причинам:

- FFmpeg уже является локальным sidecar этапа ingestion;
- не нужны `numpy`, `scipy`, `librosa`, `pydub`, `torch` или новые runtime-зависимости;
- decoder и анализ поддерживают Unicode/space paths через shell-free argv;
- фильтр не создаёт output media и не меняет источник;
- stderr содержит простые machine-like события `silence_start` и `silence_end`, которые можно разбирать отдельно от запуска процесса.

Команда использует `-f null -`, не содержит `-y`, output path, trimming или преобразующих filters. Она читает выбранный canonical stream и выбрасывает декодированные frames после измерения.

## Required parameters

`PauseSettings` поддерживает:

- `silence_threshold_db` — конечное число в диапазоне `[-120, 0)` dB;
- `minimum_pause_duration_ms` — положительное целое число миллисекунд.

Оба значения обязательны для запуска detector, но не имеют скрытых production defaults. Их нужно указать через versioned policy или техническую CLI. Пример в `config.example.toml` закомментирован и не является утверждённой продуктовой политикой.

`silence_threshold_db` определяет максимальную амплитуду, которую FFmpeg считает тишиной. `minimum_pause_duration_ms` передаётся в `silencedetect` и дополнительно проверяется после sample conversion.

## Sample conversion

FFmpeg печатает время как decimal seconds. Parser читает decimal через `Decimal`, затем преобразует его в `Fraction`; `float` не является источником времени.

Границы округляются консервативно внутрь найденного интервала:

- `start_sample = ceil(start_seconds × sample_rate)`;
- `end_sample = floor(end_seconds × sample_rate)`.

Так ограниченная точность диагностического текста FFmpeg не расширяет тишину на соседнюю речь. `PauseSegment` хранит `start_sample`, `end_sample` и `sample_rate`. `length_samples`, `start_seconds`, `end_seconds` и `duration_seconds` вычисляются из них; секундные значения представлены `Fraction`.

## Parsing and normalization

Parser не зависит от subprocess-слоя и применяет следующие правила:

1. окружающий banner, progress и неизвестные строки игнорируются;
2. распознаются стабильные токены `silence_start:` и `silence_end:` независимо от окружающего текста;
3. malformed, unpaired или обрезанные события дают `PauseDetectionError`, а не частичный выдуманный интервал;
4. интервалы сортируются по `(start_sample, end_sample)`;
5. дубликаты, пересекающиеся и соприкасающиеся интервалы объединяются;
6. интервалы короче `minimum_pause_duration_ms`, пересчитанного вверх в samples, отбрасываются;
7. отрицательные, пустые и выходящие за WAV интервалы отклоняются;
8. допускается только односэмпловая коррекция конца на границе файла для компенсации decimal log precision.

Поскольку ключевые названия генерирует сам filter, parser не зависит от языка banner/progress FFmpeg. Если будущая версия FFmpeg локализует или изменит сами ключи, contract/integration test должен зафиксировать несовместимость; молчаливое угадывание переведённых полей не выполняется.

## Known limitations

- `silencedetect` измеряет амплитудный порог, а не смысловую или естественную паузу.
- Тихое дыхание, room tone, музыка или слабая речь могут пересечь выбранный threshold.
- Начало и конец события зависят от decoder/filter time base и decimal precision stderr.
- Результат зависит от зафиксированной версии FFmpeg и параметров policy.
- Детектор не знает границы слов и не способен гарантировать безопасный монтажный разрез.
- Начальная и конечная тишина могут быть обнаружены как segments, но это не разрешает их удаление.

Поэтому найденный `PauseSegment` является только signal-level observation. Технический Stage 6 умеет детерминированно удалить только центр такого segment и явно маркирует map предупреждением об отсутствии alignment. Release-safe policy всё ещё должна сопоставить segment со STT/alignment, speech guards и правилом `no cut + warning`.

## Technical CLI

```bash
uv run --frozen python -m larp_audio_mvp.app.detect_pauses INPUT.wav \
  --silence-threshold-db -40 \
  --minimum-pause-duration-ms 500
```

Опционально доступны `--ffmpeg`, `--bundled-tools-directory` и `--timeout`. CLI печатает JSON с sample rate, total samples, параметрами и списком пауз. Успех возвращает exit code `0`; ожидаемая configuration/audio/process error — `2`.

CLI предназначена для разработческой проверки и не является GUI или пользовательским export format.
