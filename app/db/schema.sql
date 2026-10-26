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
    note           TEXT,
    exam_id        INTEGER REFERENCES exams(id) ON DELETE SET NULL   -- 검사(내원) 묶음
);

-- 검사(내원) — 환자 › 검사 › 영상 트리 (Explorer 판). 캡처 시 그날 검사가 자동으로 만들어진다.
CREATE TABLE IF NOT EXISTS exams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    exam_date   TEXT NOT NULL,               -- 'YYYY-MM-DD'
    title       TEXT,                        -- 검사명 (예: 세극등 검사)
    diagnosis   TEXT,                        -- 이번 검사의 진단·소견
    memo        TEXT,                        -- 병력·메모
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 참조 영상 라이브러리 — 질환별 대표 영상 (원본을 라이브러리 폴더에 복사해 보관)
CREATE TABLE IF NOT EXISTS ref_images (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path         TEXT NOT NULL,
    thumbnail_path    TEXT,
    category          TEXT,                  -- 분류 (각막·수정체 등)
    title             TEXT,
    description       TEXT,
    source_capture_id INTEGER,               -- 등록한 원본 캡처 (지워져도 참조 영상은 남음)
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_captures_patient ON captures(patient_id);
CREATE INDEX IF NOT EXISTS idx_captures_capdate ON captures(patient_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_patients_name    ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_chart   ON patients(chart_no);
CREATE INDEX IF NOT EXISTS idx_exams_patient    ON exams(patient_id, exam_date);
