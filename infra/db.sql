-- =============================================================================
-- LicitAI — Schema SQL Server (Azure SQL Database)
-- Versión: 0.2.2-mssql (Esquema Completo con Reset)
-- Fecha: 2026-05-21
-- Motor: SQL Server 2016+ / Azure SQL Database
-- =============================================================================

-- =============================================================================
-- 0. ZONA DE LIMPIEZA (DROP)
-- ATENCIÓN: Esto eliminará todas las tablas, vistas y sus DATOS.
-- El orden de borrado va desde las tablas hijas hacia las tablas padre.
-- =============================================================================
DROP VIEW IF EXISTS v_user_usage;
DROP VIEW IF EXISTS v_licitaciones_resumen;

DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS proposal_sections;
DROP TABLE IF EXISTS proposals;
DROP TABLE IF EXISTS citations;
DROP TABLE IF EXISTS queries;
DROP TABLE IF EXISTS match_scores;
DROP TABLE IF EXISTS pliego_summaries;
DROP TABLE IF EXISTS pliegos;
DROP TABLE IF EXISTS licitaciones;
DROP TABLE IF EXISTS company_projects;
DROP TABLE IF EXISTS company_profile;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS users;
GO

-- =============================================================================
-- 1. TABLAS BASE DE USUARIOS Y SESIONES
-- =============================================================================
CREATE TABLE users (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    email           NVARCHAR(256)    NOT NULL UNIQUE,
    password_hash   NVARCHAR(MAX)    NOT NULL, -- bcrypt/argon2 almacenado como string
    full_name       NVARCHAR(255),
    role            NVARCHAR(20)     NOT NULL DEFAULT 'user',
    is_active       BIT              NOT NULL DEFAULT 1,
    created_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    last_login_at   DATETIMEOFFSET,
    
    CONSTRAINT CK_users_role CHECK (role IN ('user', 'admin'))
);
CREATE INDEX idx_users_email ON users(email);

CREATE TABLE user_sessions (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    user_id         UNIQUEIDENTIFIER NOT NULL,
    token_hash      NVARCHAR(256)    NOT NULL UNIQUE, -- SHA-256 del token JWT
    ip_address      NVARCHAR(45),
    user_agent      NVARCHAR(MAX),
    expires_at      DATETIMEOFFSET   NOT NULL,
    revoked         BIT              NOT NULL DEFAULT 0,
    created_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_sessions_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token ON user_sessions(token_hash);

-- =============================================================================
-- 2. BASE DE CONOCIMIENTO DE LA EMPRESA (KB)
-- =============================================================================
CREATE TABLE company_profile (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    name            NVARCHAR(255)    NOT NULL,
    description     NVARCHAR(MAX)    NOT NULL,
    sectors         NVARCHAR(MAX),   -- Almacenado como JSON Array
    certifications  NVARCHAR(MAX),   -- Almacenado como JSON Array
    employee_count  INT,
    annual_revenue  DECIMAL(15,2),
    notable_clients NVARCHAR(MAX),   -- Almacenado como JSON Array
    solvency_tech   NVARCHAR(MAX),
    solvency_econ   NVARCHAR(MAX),
    profile_json    NVARCHAR(MAX),   -- JSON de esquema libre para uso del LLM
    is_default      BIT              NOT NULL DEFAULT 0,
    created_by      UNIQUEIDENTIFIER,
    updated_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_company_profile_users FOREIGN KEY (created_by) REFERENCES users(id),
    CONSTRAINT CK_profile_json CHECK (ISJSON(profile_json) > 0 OR profile_json IS NULL)
);
-- Solo permitimos un perfil por defecto (is_default = 1)
CREATE UNIQUE INDEX idx_company_profile_default ON company_profile(is_default) WHERE is_default = 1;

CREATE TABLE company_projects (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    title           NVARCHAR(512)    NOT NULL,
    description     NVARCHAR(MAX)    NOT NULL, -- Texto que se vectoriza en AI Search
    sector          NVARCHAR(255),
    client          NVARCHAR(255),
    year            INT              CHECK (year >= 1990 AND year <= 2100),
    outcome         NVARCHAR(MAX),
    tags            NVARCHAR(MAX),   -- Almacenado como JSON Array
    attachments     NVARCHAR(MAX),   -- Almacenado como JSON Array [{"filename", "blob_url"}]
    indexed_at      DATETIMEOFFSET,
    created_by      UNIQUEIDENTIFIER NOT NULL,
    created_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_projects_users FOREIGN KEY (created_by) REFERENCES users(id)
);

-- =============================================================================
-- 3. CORE DE NEGOCIO: LICITACIONES Y SUS DOCUMENTOS (PLIEGOS)
-- =============================================================================
CREATE TABLE licitaciones (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    user_id             UNIQUEIDENTIFIER NOT NULL,
    titulo              NVARCHAR(512)    NOT NULL,
    num_expediente      NVARCHAR(100),            -- Código o número oficial del concurso
    organo_contratacion NVARCHAR(255),            -- Entidad pública que convoca
    deadline            DATE,                     -- Fecha límite de presentación
    budget_amount       DECIMAL(15,2),            -- Presupuesto base sin IVA
    budget_currency     NVARCHAR(10)     DEFAULT 'EUR',
    status              NVARCHAR(20)     NOT NULL DEFAULT 'analysing',  -- estado de pipeline (processing/indexed/error)
    estado              NVARCHAR(30)     NOT NULL DEFAULT 'elaborando', -- estado comercial editable
    resultado           BIT,                       -- solo si estado='resuelta': 1=Ganada, 0=Perdida
    created_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_licitaciones_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION,
    CONSTRAINT CK_licitaciones_status CHECK (status IN ('analysing', 'bidding', 'presented', 'archived'))
);
CREATE INDEX idx_licitaciones_user ON licitaciones(user_id);

CREATE TABLE pliegos (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    licitacion_id       UNIQUEIDENTIFIER NOT NULL, -- Relación: Una licitación contiene muchos pliegos
    filename            NVARCHAR(512)    NOT NULL,
    blob_url            NVARCHAR(MAX)    NOT NULL, -- Ruta de almacenamiento en Azure Blob Storage
    blob_path           NVARCHAR(1024)   NOT NULL,
    size_bytes          BIGINT           NOT NULL CHECK (size_bytes > 0),
    mime_type           NVARCHAR(100)    NOT NULL DEFAULT 'application/pdf',
    tipo_pliego         NVARCHAR(50)     NOT NULL DEFAULT 'otros', -- PPT, PCAP, ANEXO...
    status              NVARCHAR(20)     NOT NULL DEFAULT 'uploaded',
    ocr_quality_score   DECIMAL(5,2),
    low_quality_flag    BIT              NOT NULL DEFAULT 0,
    page_count          INT,
    chunk_count         INT,                     -- Número de fragmentos indexados en AI Search
    error_message       NVARCHAR(MAX),           -- En caso de fallo en el pipeline de ingesta
    uploaded_at         DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    processed_at        DATETIMEOFFSET,
    retention_until     DATETIMEOFFSET   NOT NULL DEFAULT (DATEADD(year, 5, SYSDATETIMEOFFSET())),
    updated_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_pliegos_licitaciones FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id) ON DELETE CASCADE,
    CONSTRAINT CK_pliegos_status CHECK (status IN ('uploaded', 'processing', 'indexed', 'error')),
    CONSTRAINT CK_pliegos_tipo CHECK (tipo_pliego IN ('PCAP', 'PPT', 'ANEXO', 'OTROS'))
);
CREATE INDEX idx_pliegos_licitacion ON pliegos(licitacion_id);

-- =============================================================================
-- 4. INTELIGENCIA ARTIFICIAL: RESÚMENES, EVALUACIONES Y RAG
-- =============================================================================
CREATE TABLE pliego_summaries (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    pliego_id           UNIQUEIDENTIFIER NOT NULL UNIQUE, -- Un resumen detallado por documento
    technical_solvency  NVARCHAR(MAX),
    economic_solvency   NVARCHAR(MAX),
    contract_duration   NVARCHAR(500),
    award_criteria      NVARCHAR(MAX),   -- JSON estructurado con los criterios de puntuación
    key_requirements    NVARCHAR(MAX),   -- JSON estructurado de requisitos críticos del documento
    raw_summary_text    NVARCHAR(MAX),   -- Resumen ejecutivo en texto libre generado por el LLM
    model_used          NVARCHAR(100),
    generated_at        DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_summaries_pliegos FOREIGN KEY (pliego_id) REFERENCES pliegos(id) ON DELETE CASCADE,
    CONSTRAINT CK_summaries_award CHECK (ISJSON(award_criteria) > 0 OR award_criteria IS NULL),
    CONSTRAINT CK_summaries_reqs CHECK (ISJSON(key_requirements) > 0 OR key_requirements IS NULL)
);

CREATE TABLE match_scores (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    licitacion_id       UNIQUEIDENTIFIER NOT NULL, -- El encaje se evalúa para todo el concurso público
    user_id             UNIQUEIDENTIFIER NOT NULL,
    company_profile     NVARCHAR(MAX)    NOT NULL, 
    score               DECIMAL(5,2)     NOT NULL CHECK (score >= 0 AND score <= 100),
    justification       NVARCHAR(MAX)    NOT NULL,
    fulfilled           NVARCHAR(MAX),   -- JSON de requisitos cumplidos
    missing             NVARCHAR(MAX),   -- JSON de requisitos no cumplidos
    uncertain           NVARCHAR(MAX),   -- JSON de dudas/riesgos
    model_used          NVARCHAR(100),
    calculated_at       DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_match_licitaciones FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id) ON DELETE CASCADE,
    CONSTRAINT FK_match_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION
);

CREATE TABLE queries (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    licitacion_id       UNIQUEIDENTIFIER NOT NULL, -- Consultas cruzadas sobre todos los pliegos indexados
    user_id             UNIQUEIDENTIFIER NOT NULL,
    question            NVARCHAR(MAX)    NOT NULL,
    answer              NVARCHAR(MAX)    NOT NULL,
    chunk_ids           NVARCHAR(MAX),   -- JSON Array con los IDs del índice vectorial externo
    chunk_scores        NVARCHAR(MAX),   -- JSON Array de scores de relevancia correlacionados
    model_used          NVARCHAR(100)    NOT NULL,
    tokens_prompt       INT,
    tokens_completion   INT,
    latency_ms          INT,
    had_citations       BIT              NOT NULL DEFAULT 0,
    is_unanswerable     BIT              NOT NULL DEFAULT 0,
    created_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_queries_licitaciones FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id) ON DELETE CASCADE,
    CONSTRAINT FK_queries_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION
);

CREATE TABLE citations (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    query_id        UNIQUEIDENTIFIER NOT NULL,
    chunk_id        NVARCHAR(255)    NOT NULL,
    page_number     INT              NOT NULL, -- Página del documento físico de donde proviene la verdad
    relevance_score DECIMAL(5,4),
    is_valid        BIT              NOT NULL DEFAULT 1,

    CONSTRAINT FK_citations_queries FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE CASCADE
);

-- =============================================================================
-- 5. GENERACIÓN AUTOMATIZADA DE PROPUESTAS TÉCNICAS
-- =============================================================================
CREATE TABLE proposals (
    id              UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    licitacion_id   UNIQUEIDENTIFIER NOT NULL, -- La propuesta responde al concurso global
    user_id         UNIQUEIDENTIFIER NOT NULL,
    title           NVARCHAR(512)    NOT NULL,
    tone            NVARCHAR(20)     NOT NULL DEFAULT 'técnico',
    status          NVARCHAR(20)     NOT NULL DEFAULT 'generating',
    model_used      NVARCHAR(100),
    total_tokens    INT,
    approved_by     UNIQUEIDENTIFIER NULL,
    approved_at     DATETIMEOFFSET,
    created_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_proposals_licitaciones FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id) ON DELETE CASCADE,
    CONSTRAINT FK_proposals_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION,
    CONSTRAINT CK_proposals_tone CHECK (tone IN ('ejecutivo', 'técnico', 'comercial')),
    CONSTRAINT CK_proposals_status CHECK (status IN ('generating', 'draft', 'review', 'approved', 'archived'))
);

CREATE TABLE proposal_sections (
    id                  UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    proposal_id         UNIQUEIDENTIFIER NOT NULL,
    order_index         INT              NOT NULL,
    title               NVARCHAR(512)    NOT NULL,
    content             NVARCHAR(MAX)    NOT NULL DEFAULT '', -- Contenido editable por el usuario
    content_llm         NVARCHAR(MAX),                        -- Respaldo original sin alteraciones humanas
    generated_by_llm    BIT              NOT NULL DEFAULT 0,
    reviewed            BIT              NOT NULL DEFAULT 0,
    -- Columna calculada de forma dinámica para estimar palabras
    word_count          AS (LEN(content) - LEN(REPLACE(content, ' ', '')) + 1),
    created_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at          DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_sections_proposals FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE CASCADE,
    CONSTRAINT UQ_proposal_order UNIQUE (proposal_id, order_index)
);

-- =============================================================================
-- 6. AUDITORÍA INMUTABLE (RGPD Y TRAZABILIDAD)
-- =============================================================================
CREATE TABLE audit_log (
    id              BIGINT IDENTITY(1,1) PRIMARY KEY,
    user_id         UNIQUEIDENTIFIER NULL,
    actor           NVARCHAR(255),                        -- Ej: email o identificador del sistema/pipeline
    action          NVARCHAR(100)    NOT NULL,            -- Ej: 'licitacion.upload', 'proposal.approve'
    resource_type   NVARCHAR(50)     NOT NULL,            -- Ej: 'licitacion', 'query', 'user'
    resource_id     UNIQUEIDENTIFIER,
    detail          NVARCHAR(MAX),                        -- JSON estructurado libre de datos sensibles
    ip_address      NVARCHAR(45),                         -- Soporta formatos IPv4 e IPv6
    created_at      DATETIMEOFFSET   NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT FK_audit_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT CK_audit_detail CHECK (ISJSON(detail) > 0 OR detail IS NULL)
);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);

-- =============================================================================
-- 7. LOGICA DE TRIGGERS (MANTENIMIENTO AUTOMÁTICO DE UPDATED_AT)
-- T-SQL requiere un bloque individual por cada tabla.
-- =============================================================================
GO

CREATE TRIGGER trg_users_updated_at ON users AFTER UPDATE AS
BEGIN
    UPDATE users SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE users.id = i.id;
END;
GO

CREATE TRIGGER trg_company_profile_updated_at ON company_profile AFTER UPDATE AS
BEGIN
    UPDATE company_profile SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE company_profile.id = i.id;
END;
GO

CREATE TRIGGER trg_company_projects_updated_at ON company_projects AFTER UPDATE AS
BEGIN
    UPDATE company_projects SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE company_projects.id = i.id;
END;
GO

CREATE TRIGGER trg_licitaciones_updated_at ON licitaciones AFTER UPDATE AS
BEGIN
    UPDATE licitaciones SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE licitaciones.id = i.id;
END;
GO

CREATE TRIGGER trg_pliegos_updated_at ON pliegos AFTER UPDATE AS
BEGIN
    UPDATE pliegos SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE pliegos.id = i.id;
END;
GO

CREATE TRIGGER trg_proposals_updated_at ON proposals AFTER UPDATE AS
BEGIN
    UPDATE proposals SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE proposals.id = i.id;
END;
GO

CREATE TRIGGER trg_proposal_sections_updated_at ON proposal_sections AFTER UPDATE AS
BEGIN
    UPDATE proposal_sections SET updated_at = SYSDATETIMEOFFSET() FROM Inserted i WHERE proposal_sections.id = i.id;
END;
GO

-- =============================================================================
-- 8. VISTAS ANALÍTICAS Y DE UTILIDAD
-- =============================================================================
GO

-- Vista: Cuadro de mandos de licitaciones y consolidación de páginas de sus pliegos
CREATE VIEW v_licitaciones_resumen AS
SELECT 
    l.id AS licitacion_id,
    l.titulo,
    l.num_expediente,
    l.organo_contratacion,
    l.deadline,
    l.budget_amount,
    l.budget_currency,
    l.status,
    COUNT(p.id) AS total_pliegos,
    SUM(ISNULL(p.page_count, 0)) AS total_paginas_licitacion
FROM licitaciones l
LEFT JOIN pliegos p ON l.id = p.licitacion_id
GROUP BY 
    l.id, l.titulo, l.num_expediente, l.organo_contratacion, 
    l.deadline, l.budget_amount, l.budget_currency, l.status;
GO

-- Vista: Métricas agregadas de consumo e interacción por cliente/usuario
CREATE VIEW v_user_usage AS
SELECT 
    u.id AS user_id,
    u.email,
    COUNT(DISTINCT l.id) AS total_licitaciones,
    COUNT(DISTINCT p.id) AS total_pliegos_subidos,
    COUNT(DISTINCT q.id) AS total_consultas_rag,
    COUNT(DISTINCT pr.id) AS total_propuestas_generadas,
    SUM(ISNULL(q.tokens_prompt + q.tokens_completion, 0)) AS total_tokens_consumidos
FROM users u
LEFT JOIN licitaciones l ON l.user_id = u.id
LEFT JOIN pliegos p ON p.licitacion_id = l.id
LEFT JOIN queries q ON q.user_id = u.id
LEFT JOIN proposals pr ON pr.user_id = u.id
GROUP BY u.id, u.email;
GO

-- =============================================================================
-- DATA SEED (DATOS SEMILLA INICIALES)
-- =============================================================================
INSERT INTO company_profile (name, description, is_default)
VALUES (
    'Mi Empresa',
    'Descripción de la empresa: sector, especialización, alcance de servicios.',
    1
);
GO
