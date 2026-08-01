# Runbook de seguridad

## P0 — Llave de proveedor expuesta en historial Git

El repositorio es público y tres commits históricos (`8d66b97`, `6202a9f` y
`9977a2f`) contienen un `backend/.env` con una `EMERGENT_LLM_KEY` no vacía. No
copies ni vuelvas a mostrar el valor: debe tratarse como comprometido aunque ya
no exista en HEAD.

Acciones del owner, en este orden:

1. Revocar la llave en el proveedor y, solo si la integración demo sigue siendo
   necesaria, crear otra con alcance/cuota mínimos en el gestor de secretos.
2. Revisar uso, facturación y logs desde el 15-09-2025; conservar evidencia de
   actividad anómala y registrar fecha/persona de la rotación.
3. Verificar que Render, Netlify, GitHub Actions y equipos locales no sigan
   usando la llave revocada.
4. Ejecutar secret scanning sobre HEAD, ramas, tags e historial completo.
5. Decidir con todos los colaboradores si se reescribe la historia. Revocar es
   obligatorio y va primero; borrar blobs históricos no vuelve segura una llave
   que ya fue pública. Una limpieza exige backup, coordinación, force-push,
   recrear clones/forks y revisar PRs abiertos.

No hay secretos actuales detectados en HEAD durante la auditoría del 01-08-2026.
Eso no cierra el incidente histórico.

## Antes de promover datos a producción

- Crear snapshot verificable de Atlas y ensayar restore.
- Inventariar documentos legacy de `users` sin `rut_key`/`email_key` y de
  `members` sin procedencia; no asumir que las altas antiguas están cifradas o
  verificadas.
- Resolver duplicados antes de crear índices únicos.
- Ensayar migración con claves del gestor de secretos, validar conteos/campos y
  documentar rollback. Esta rama cuarentena miembros demo/legacy, pero no cifra
  automáticamente PII histórica.
