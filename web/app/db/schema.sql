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
    file_path      TEXT NOT NULL,            -- 서버 저장 상대 경로
    url            TEXT NOT NULL,            -- 브라우저 접근 URL
    captured_at    TEXT NOT NULL,            -- 'YYYY-MM-DD HH:MM:SS'
    eye            TEXT CHECK (eye IN ('OD','OS','OU','NA') OR eye IS NULL),
    duration_ms    INTEGER,                  -- 동영상만
    note           TEXT
);

-- 측정 기록 (수정체 혼탁 지수 등) — 경과 그래프 + 의사 입력 LOCS III 등급(라벨 데이터)
CREATE TABLE IF NOT EXISTS measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    capture_id  INTEGER REFERENCES captures(id) ON DELETE SET NULL,
    eye         TEXT,
    kind        TEXT NOT NULL,               -- nuclear | cortical | fluorescein | redness
    value       REAL NOT NULL,               -- 지수(0~100) / 면적 %
    detail      TEXT,                        -- JSON (비율·밝기·동공 직경 등)
    locs        TEXT,                        -- JSON 의사 입력 LOCS III 등급
    conditions  TEXT,                        -- 촬영 조건 메모 (슬릿 폭·각도·배율·노출)
    measured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_measure_patient ON measurements(patient_id, kind, eye, measured_at);
-- 참조 샘플 (부위별 · 정상/비정상 대표 영상) — 환자와 무관한 비교용 라이브러리
CREATE TABLE IF NOT EXISTS ref_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    region      TEXT NOT NULL,               -- eyelid | conjunctiva | cornea | ac | iris | lens | meibo | other
    condition   TEXT NOT NULL CHECK (condition IN ('normal','abnormal')),
    disease     TEXT,                        -- 비정상일 때 질환명 (사용자가 붙이는 분류 이름)
    note        TEXT,
    file_path   TEXT NOT NULL,
    url         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ref_region ON ref_samples(region, condition);
CREATE INDEX IF NOT EXISTS idx_captures_patient ON captures(patient_id);
CREATE INDEX IF NOT EXISTS idx_captures_capdate ON captures(patient_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_patients_name    ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_chart   ON patients(chart_no);
