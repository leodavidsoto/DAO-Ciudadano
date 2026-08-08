# ADR-004: Observabilidad, Monitoreo y Guardrails

**Estado:** Aceptado
**Fecha:** 2026-08-04

## Contexto

El sistema gestiona identidad cívica y participación democrática. Caídas del servicio o cuellos de botella no detectados pueden deslegitimar una votación o dejar a ciudadanos sin poder autenticarse. Actualmente, los logs se imprimen de forma estructurada pero no son agregados. La validación `readiness.py` asegura que las variables críticas existan antes de arrancar, pero no hay monitoreo continuo.

Debemos definir el stack de observabilidad y las políticas de despliegue para garantizar la disponibilidad en producción, y evaluar si la infraestructura actual (Render Free Tier) cumple con el SLA esperado.

## Decisiones

### 1. Stack de Observabilidad
- **Métricas, Tracing y Logs:** Se adoptará **OpenTelemetry (OTel)** como estándar de instrumentación en el backend de FastAPI. Esto evitará el vendor lock-in.
- **Backend de Observabilidad:** Se enviarán los datos OTel a un SaaS gestionado, priorizando **Sentry** para seguimiento de errores y rendimiento de API. No se hospedará una instancia local de Prometheus/Grafana temporalmente para evitar carga operativa en el equipo de mantención.
- **Monitoreo de Nodos Blockchain:** Se configurarán alertas en **Alchemy/Infura** (vía webhooks) para caídas del RPC o límites de cuota que impidan el minteo o validación de on-chain (ej: fallos repetidos en `hasMembership`).

### 2. Guardrails y Niveles de Servicio (SLA)
- **Infraestructura Actual:** El proyecto actualmente corre en Render Free Tier para validaciones piloto. **Conclusión:** Render Free Tier (con suspensiones tras inactividad y límites de RAM) **no es apto** para un entorno de producción donde los ciudadanos emiten votos en marcos de tiempo restringidos.
- **Evolución:** El despliegue de producción requerirá:
  1. Instancias con autoescalado (ej. AWS ECS, GCP Cloud Run o un tier pago en Render/Railway).
  2. Redundancia de RPC (failover automático entre dos proveedores como Alchemy y PublicNode).
  3. Base de datos MongoDB Atlas en un clúster dedicado de alta disponibilidad.

## Consecuencias
- Añadiremos instrumentación de OpenTelemetry al backend.
- Dejaremos constancia explícita de que el despliegue final en Mainnet no puede ocurrir en la infraestructura gratuita actual.
- Mantendremos la confianza de los ciudadanos al asegurar que los tiempos de respuesta y fallas sean detectados y resueltos ágilmente.
