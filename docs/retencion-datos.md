# Políticas de Retención de Datos y Cumplimiento Legal

En cumplimiento con los requisitos de la Ley de Contratos del Sector Público (LCSP) y el Reglamento General de Protección de Datos (RGPD), el sistema **LicitAI** tiene configuradas y activadas a nivel de infraestructura las siguientes políticas automatizadas de retención:

## 1. Almacenamiento de Pliegos (Azure Blob Storage)
Se ha configurado una directiva de administración del ciclo de vida (Lifecycle Management) a nivel de *storage account* para garantizar la correcta depuración de los documentos físicos (archivos PDF):
* **Retención máxima legal (LCSP):** Todos los blobs se eliminan de forma automática y definitiva a los **5 años (1825 días)** desde su fecha de creación.
* **Derecho al olvido / Borrado lógico:** Si un documento es eliminado del sistema de forma explícita, este pasa a un estado de eliminación temporal y es purgado definitivamente de los servidores a los **30 días**.

## 2. Base de Datos y Backups (Azure SQL Database)
Para garantizar el aislamiento y la privacidad de los metadatos de los pliegos y la información de los usuarios:
* **Copias de seguridad (PITR):** La directiva de retención de las copias de seguridad automatizadas a un momento dado de la base de datos está configurada con un límite estricto de **30 días**. Superado este periodo, los backups antiguos se destruyen automáticamente de forma irrecuperable.
