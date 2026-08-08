# Auditoría de Infraestructura y SLA (Render Free Tier)

Este documento forma parte de la **Fase 5.3**, evaluando la idoneidad del entorno actual en Render (Free Tier) para el lanzamiento en producción de la DAO Ciudadana y documentando los límites operativos (guardrails).

## Guardrails Implementados
Actualmente el backend cuenta con los siguientes mecanismos de defensa que protegen contra abusos y caídas en infraestructura limitada:
1. **Rate Limiting (Redis):** Middleware global en FastAPI (ventanas deslizantes Lua) para proteger contra ataques DDoS en los endpoints de lectura.
2. **Body Size Limiter:** Límite de carga estricto de 2MB por petición para evitar OOM (Out Of Memory) en servidores de bajos recursos.
3. **Caché Distribuido (TTL = 60s):** Los requests al Safe Multisig y CoinGecko están oxigenados con caché. En un escenario de tráfico alto, el impacto hacia los RPC de web3 no escala de forma lineal.
4. **Protección Sybil (Voto MACI):** El conteo descarta firmas no válidas y mitiga el flood sin golpear la base de datos más allá de lo necesario.

## Evaluación de SLA sobre Render (Free Tier)
Actualmente, el backend de la DAO Ciudadana se aloja en el servicio gratuito de Render, el cual otorga 512 MB de RAM y sufre de *cold starts* (apagado por inactividad tras 15 minutos).

### Limitaciones Identificadas
1. **Arranque en Frío (Cold Start):** El ciudadano experimentará latencias iniciales de 20 a 50 segundos si es el primero en interactuar. En el contexto de criptografía ZK, esto impactará severamente el UX.
2. **Memoria Restringida (512MB):** Operaciones pesadas (validación concurrente del Snark Tally) amenazan con alcanzar el límite de memoria, desencadenando un reinicio OOM.
3. **Caídas no anunciadas:** Render detiene las máquinas sin aviso al final del mes si se acaba el presupuesto de 750 horas, lo que interrumpe el quorum en días electorales.

### Decisión de Producción
El **Free Tier de Render NO es adecuado** para el SLA que requiere un sistema de gobernanza en red principal. 
Para el despliegue de Mainnet, se requerirá un salto mínimo a infraestructura dedicada (ej. Render Pro o AWS ECS) para garantizar alta disponibilidad (99.9% uptime) durante periodos de votación masiva. Los guardrails actuales aseguran que, al mudarnos, el software por debajo está diseñado para soportar picos y no abusará del servidor, sin importar la capacidad del metal.
