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
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS captures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id     INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    media_type     TEXT NOT NULL CHECK (media_type IN ('photo','video')),
    file_path      TEXT NOT NULL,            -- 서버 저장 상대 경로
    url            TEXT NOT NULL,            -- 브라우저 접근 URL
    captured_at    TEXT NOT NULL,            -- 'YYYY-MM-DD HH:MM:SS'
    eye            TEXT CHECK (eye IN ('OD','OS','OU','NA') OR eye IS NULL),
    duration_ms    INTEGER,                  -- 동영상만
    note           TEXT
);

CREATE INDEX IF NOT EXISTS idx_captures_patient ON captures(patient_id);
CREATE INDEX IF NOT EXISTS idx_captures_capdate ON captures(patient_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_patients_name    ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_chart   ON patients(chart_no);
