# Cómo trabajamos en LicitAI

Este documento define cómo colaboramos los 3 desarrolladores en el proyecto. Es corto a propósito. Si tienes dudas y no están aquí, pregunta en el grupo y lo añadimos.

## 1. Flujo de trabajo

Todo el trabajo nace de un **issue** en GitHub Projects. No se trabaja "a piñón", se trabaja sobre algo que está en el board.

```
Issue (To Do)  →  Rama  →  Commits  →  Pull Request  →  Review  →  Merge a main  →  Issue cerrado
```

### Pasos concretos

1. **Coge un issue** de la columna *To Do* y muévelo a *In Progress*. Asígnatelo a ti mismo.
2. **Crea una rama** desde `main` actualizado:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/HU-XX-descripcion-corta
   ```
3. **Trabaja y commitea** siguiendo las convenciones de abajo.
4. **Abre un Pull Request** cuando esté listo. Mueve el issue a *In Review*.
5. **Espera al menos 1 aprobación** de otro miembro del equipo antes de mergear.
6. **Mergea con squash** a `main`. Borra la rama remota.
7. **Cierra el issue** (se cierra solo si pones `Closes #N` en la descripción del PR).

## 2. Ramas

Formato: `tipo/HU-XX-descripcion-corta-en-ingles`

| Tipo | Cuándo |
|---|---|
| `feature/` | Nueva funcionalidad |
| `fix/` | Arreglar un bug |
| `chore/` | Tareas de mantenimiento, dependencias, configuración |
| `docs/` | Solo cambios de documentación |
| `refactor/` | Reorganización de código sin cambio de comportamiento |

**Ejemplos:**
- `feature/HU-INF-05-smoke-test-e2e`
- `fix/HU-12-pdf-parser-empty-pages`
- `chore/upgrade-fastapi-to-0.115`
- `docs/architecture-overview`

**Nunca** se hace push directo a `main`. Nunca.

## 3. Commits

Convención: [Conventional Commits](https://www.conventionalcommits.org/).

```
tipo: descripción corta en presente

Cuerpo opcional explicando el qué y el por qué.
```

| Tipo | Cuándo |
|---|---|
| `feat` | Nueva funcionalidad |
| `fix` | Arreglo de bug |
| `docs` | Solo documentación |
| `chore` | Tareas auxiliares |
| `refactor` | Refactor sin cambio funcional |
| `test` | Añadir o modificar tests |
| `style` | Formato, lint (sin cambios de lógica) |

**Ejemplos:**
- `feat: add document upload endpoint`
- `fix: handle scanned PDFs without OCR layer`
- `docs: update setup instructions for Azure CLI`

Commits cortos, atómicos, en inglés. Si necesitas explicar mucho, va en el cuerpo del commit o en el PR.

## 4. Pull Requests

### Reglas

- **Tamaño máximo**: ~400 líneas tocadas. Si es más, parte el PR.
- **Mínimo 1 reviewer** que apruebe antes de mergear.
- **CI en verde** obligatorio (cuando esté montado).
- **Merge con squash**, no merge commit ni rebase merge. Mantiene el historial de `main` limpio.
- **Borrar la rama** después de mergear.

### Reviews

- Si te asignan un PR, **revísalo en menos de 24 horas** o avisa.
- Aprobar o pedir cambios, no dejar PRs en limbo.
- Comentarios concretos y constructivos. Si es algo opcional, prefijar con "nit:" (nitpick).
- Si llevas más de 3 días sin que te aprueben un PR, da un toque en el grupo.

## 5. Definition of Done

Una historia/tarea está **terminada** cuando se cumple TODO esto:

- [ ] El código está mergeado a `main`
- [ ] Los criterios de aceptación del issue se cumplen
- [ ] El PR ha sido revisado y aprobado por al menos 1 compañero
- [ ] Si añade lógica nueva, hay al menos un test que la cubra (cuando tengamos CI)
- [ ] La documentación afectada está actualizada
- [ ] No quedan secretos hardcodeados ni `print()` de debug
- [ ] El issue está cerrado y movido a *Done* en el Project

## 6. Comunicación

- **Daily asíncrono** en el grupo: cada uno escribe qué hizo ayer, qué hace hoy, qué le bloquea. Sin formato rígido.
- **Sync síncrono** 2-3 veces por semana, 15 minutos máximo. Antes de cada sprint planning, 1 hora.
- **Si estás bloqueado más de 2 horas**, escríbelo en el grupo. No sufras solo.
- **Decisiones técnicas relevantes** se documentan en `docs/ADR/` (Architecture Decision Records).

## 7. Setup local

Ver `README.md` para instrucciones de setup.

Variables de entorno: copiar `backend/.env.example` a `backend/.env` y rellenar con los valores que están en Key Vault. Nunca subir `.env` al repo.

## 8. Convención de nombres en código

- **Python**: `snake_case` para variables y funciones, `PascalCase` para clases
- **TypeScript**: `camelCase` para variables y funciones, `PascalCase` para componentes y tipos
- **Archivos Python**: `snake_case.py`
- **Archivos TS/React**: `PascalCase.tsx` para componentes, `camelCase.ts` para utilidades
- **Variables de entorno**: `UPPER_SNAKE_CASE`
- **Branches y commits**: en inglés siempre

## 9. Reglas de oro

1. **Si tu rama lleva más de 3 días sin mergear**, rebasea contra `main` para evitar conflictos masivos.
2. **Nunca subas un secreto al repo.** Si lo haces por error, avisa en el grupo y lo rotamos.
3. **Antes de empezar a trabajar en algo grande**, coméntalo en el grupo. Evita duplicar esfuerzo.
4. **Si rompes `main`**, es tu prioridad arreglarlo. Para todos.
5. **Pregunta antes que asumir.** Mejor 5 minutos en el grupo que 5 horas reescribiendo.
