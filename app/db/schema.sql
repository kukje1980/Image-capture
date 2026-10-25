PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_no    TEXT UNIQUE,                 -- 차트번호
    patient_id  TEXT,                        -- 환자ID(선택)
    name        TEXT NOT NULL,
    birth_date  TEXT,                        -- 'YYYY-MM-DD'
    sex         TEXT CHECK (sex IN ('M','F','O') OR sex IS NULL),
    phone       TEXT,
    memo        TEXT,
    symptoms    TEXT,                        -- 증상/기타
    diagnosis   TEXT,                        -- 진단명
    doctor      TEXT,                        -- 담당의
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS captures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    media_type     TEXT NOT NULL CHECK (media_type IN ('photo','video')),
    file_path      TEXT NOT NULL,            -- 기본 저장 경로
    export_path    TEXT,                     -- 지정 폴더 복사본(실패 시 NULL)
    thumbnail_path TEXT,
    captured_at    TEXT NOT NULL,            -- 'YYYY-MM-DD HH:MM:SS'
    eye            TEXT CHECK (eye IN ('OD','OS','OU','NA') OR eye IS NULL),
    duration_ms    INTEGER,                  -- 동영상만
    note           TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    capture_id  INTEGER REFERENCES captures(id) ON DELETE SET NULL,
    eye         TEXT,
    kind        TEXT NOT NULL,               -- nuclear | cortical | fluorescein | redness
    value       REAL NOT NULL,               -- 지수(0~100) / 면적 %
    detail      TEXT,                        -- JSON (비율·밝기·동공 직경 등)
    locs        TEXT,                        -- JSON 의사 입력 LOCS III 등급 (라벨 데이터)
    conditions  TEXT,                        -- 촬영 조건 메모 (슬릿 폭·각도·배율·노출)
    measured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_measure_patient ON measurements(patient_id, kind, eye, measured_at);
CREATE INDEX IF NOT EXISTS idx_captures_patient ON captures(patient_id);
CREATE INDEX IF NOT EXISTS idx_captures_capdate ON captures(patient_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_patients_name    ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_chart   ON patients(chart_no);
