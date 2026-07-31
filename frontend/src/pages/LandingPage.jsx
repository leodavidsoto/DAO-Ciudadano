/**
 * Landing pública de EstamosDAO.
 *
 * Adaptada del mockup `EstamosDAO Landing.dc.html` (design system Nocturne).
 * El mockup venía como HTML de Claude Design con runtime propio: etiquetas
 * <x-dc>/<sc-for>/<sc-if>, interpolaciones {{ }} y un atributo `style-hover`.
 * Nada de eso funciona fuera de ese editor, así que acá está convertido a
 * React de verdad: los bucles son .map(), el estado es useState y los hover
 * viven en styles/landing.css.
 *
 * Es la ruta "/" del sitio. El CTA "ÚNETE A LA RED" lleva a /unete, que es
 * el flujo de onboarding que ya existía (antes colgaba de "/").
 *
 * SOBRE LAS CIFRAS: la banda de estadísticas consulta los endpoints reales
 * (/dashboard/stats y /governance/stats). Mientras carga, o si la API no
 * responde, muestra "—" en vez de números inventados: este repositorio ya
 * arrastraba hallazgos de auditoría por mostrar cifras fabricadas, y una
 * landing pública es justo donde más daño hace. El resto del contenido
 * (propuestas de ejemplo, votación en vivo) está rotulado como muestra.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { dashboardAPI, governanceAPI } from '../lib/api';
import '../styles/landing.css';

const AZUL = '#003897';
const ROJO = '#CB2C27';
const TINTA = '#0B2545';

/** Propuestas ilustrativas del mockup. No vienen de la API — ver el rótulo
 *  "DATOS DE EJEMPLO" en el hero. */
const PROPUESTAS_DEMO = [
    {
        code: '#087',
        title: 'Ciclovías conectadas en Ñuñoa',
        desc: 'Red de 14 km de ciclovías protegidas entre Plaza Ñuñoa y Estadio Nacional.',
        status: 'En votación',
        place: 'Ñuñoa',
        region: 'Región Metropolitana',
        pct: 78,
        mapY: 30,
        meta: 'Cierra en 2 días',
    },
    {
        code: '#091',
        title: 'Fomento al emprendimiento local',
        desc: 'Fondo rotatorio de microcréditos para ferias y almacenes de barrio.',
        status: 'En debate',
        place: 'Valparaíso',
        region: 'Región de Valparaíso',
        pct: 34,
        mapY: 22,
        meta: 'Debate abierto · 41 aportes',
    },
    {
        code: '#079',
        title: 'Protección de humedales urbanos',
        desc: 'Plan de restauración y monitoreo ciudadano de tres humedales costeros.',
        status: 'Aprobada',
        place: 'Valdivia',
        region: 'Región de Los Ríos',
        pct: 100,
        mapY: 46,
        meta: 'Ejecución en curso',
    },
];

const COLORES_ESTADO = {
    'En votación': { tagBg: '#EAF0FB', tagFg: '#003897', tagDot: '#003897', barColor: '#003897' },
    'En debate': { tagBg: '#FBEAE8', tagFg: '#A9211D', tagDot: '#CB2C27', barColor: '#CB2C27' },
    Aprobada: { tagBg: '#E9F1EC', tagFg: '#1F6B45', tagDot: '#2E8B57', barColor: '#2E8B57' },
};

const FILTROS = ['Todas', 'En votación', 'En debate'];

const PASOS = [
    { icon: 'ph-note-pencil', n: 1, title: 'Presenta tu idea', desc: 'Redacta la propuesta y define presupuesto y comuna.', color: AZUL },
    { icon: 'ph-chats-circle', n: 2, title: 'Debatamos en red', desc: 'Siete días de discusión abierta y enmiendas de la comunidad.', color: AZUL },
    { icon: 'ph-check-square-offset', n: 3, title: 'Vota con transparencia', desc: 'Un voto por ciudadano verificado, registrado en cadena.', color: ROJO },
    { icon: 'ph-gear-six', n: 4, title: 'Ejecutemos el cambio', desc: 'Los fondos se liberan por hitos verificables y públicos.', color: ROJO },
];

const PILARES = [
    { icon: 'ph-users-three', bg: '#EAF0FB', fg: AZUL, title: 'Decisión colectiva', desc: 'Todos los miembros verificados tienen voz y voto en las propuestas que afectan a su comuna.' },
    { icon: 'ph-cube-transparent', bg: '#FBEAE8', fg: ROJO, title: 'Transparencia blockchain', desc: 'Cada voto y cada peso asignado queda inmutable y auditable por cualquier ciudadano.' },
    { icon: 'ph-buildings', bg: '#EAF0FB', fg: AZUL, title: 'Acción comunitaria', desc: 'Los proyectos aprobados se ejecutan con fondos liberados por la propia comunidad.' },
];

const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('es-CL') : '—');

const LandingPage = () => {
    const navigate = useNavigate();

    const [filtro, setFiltro] = useState('Todas');
    // Widget de votación de muestra: reacciona al click para que se sienta
    // vivo, pero no escribe nada en la cadena ni en la API.
    const [forPct, setForPct] = useState(62);
    const [votos, setVotos] = useState(4318);
    const [stats, setStats] = useState(null);

    useEffect(() => {
        let vivo = true;
        Promise.all([
            dashboardAPI.getStats().catch(() => null),
            governanceAPI.getStats().catch(() => null),
        ]).then(([dash, gov]) => {
            if (!vivo) return;
            setStats({
                miembros: dash?.data?.total_members ?? null,
                propuestas: gov?.data?.total_proposals ?? null,
                aprobadas: gov?.data?.passed_proposals ?? null,
                votos: gov?.data?.total_votes_cast ?? null,
            });
        });
        return () => { vivo = false; };
    }, []);

    const propuestas = useMemo(
        () => PROPUESTAS_DEMO.map((p) => ({ ...p, ...COLORES_ESTADO[p.status] })),
        [],
    );
    const mostradas = filtro === 'Todas' ? propuestas : propuestas.filter((p) => p.status === filtro);

    const irAUnirse = () => navigate('/unete');

    const kpis = [
        { valor: fmt(stats?.miembros), etiqueta: 'ciudadanos verificados' },
        { valor: fmt(stats?.propuestas), etiqueta: 'propuestas presentadas' },
        { valor: fmt(stats?.aprobadas), etiqueta: 'propuestas aprobadas' },
        { valor: fmt(stats?.votos), etiqueta: 'votos emitidos' },
    ];

    return (
        <div className="landing-root">
            <div style={{ maxWidth: 1440, margin: '0 auto', overflowX: 'hidden' }}>

                {/* ===== Header ===== */}
                <header
                    className="landing-header"
                    style={{
                        position: 'sticky', top: 0, zIndex: 20, display: 'flex', alignItems: 'center',
                        flexWrap: 'wrap', rowGap: 10, columnGap: 'clamp(16px, 2vw, 32px)',
                        padding: '14px 48px', background: 'rgba(255,255,255,0.94)',
                        backdropFilter: 'blur(10px)', borderBottom: '1px solid #E5EBF5',
                    }}
                >
                    <a href="#inicio" style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                        <img
                            src="/assets/logo-mark.png"
                            alt="EstamosDAO Chile"
                            style={{ width: 46, height: 46, objectFit: 'contain', display: 'block' }}
                        />
                        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
                            <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 21, letterSpacing: '-0.02em', color: TINTA }}>
                                Estamos<span style={{ fontWeight: 700, color: AZUL }}>DAO</span>
                            </span>
                            <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 10, fontWeight: 500, letterSpacing: '0.28em', color: '#5C7099', marginTop: 3 }}>
                                CHILE
                            </span>
                        </span>
                    </a>

                    <nav
                        className="landing-nav"
                        style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'flex-end', flex: '1 1 auto',
                            gap: 'clamp(12px, 1.5vw, 26px)', minWidth: 0, whiteSpace: 'nowrap',
                            fontFamily: 'Poppins, sans-serif', fontSize: 'clamp(10.5px, 0.95vw, 12.5px)',
                            fontWeight: 500, letterSpacing: '0.08em',
                        }}
                    >
                        <a href="#inicio" className="landing-nav-link is-active">INICIO</a>
                        <a href="#propuestas" className="landing-nav-link">PROPUESTAS</a>
                        <a href="#como" className="landing-nav-link">CÓMO FUNCIONA</a>
                        <a href="#comunidad" className="landing-nav-link">COMUNIDAD</a>
                    </nav>

                    <button
                        type="button"
                        onClick={irAUnirse}
                        className="landing-btn-primary"
                        style={{
                            flexShrink: 0, cursor: 'pointer', border: 'none',
                            fontFamily: 'Poppins, sans-serif', fontSize: 12.5, fontWeight: 600,
                            letterSpacing: '0.09em', padding: '13px 22px', whiteSpace: 'nowrap',
                            borderRadius: 999, boxShadow: '0 6px 16px rgba(0,56,151,0.22)',
                        }}
                    >
                        ÚNETE A LA RED
                    </button>
                </header>

                {/* ===== Hero ===== */}
                <section
                    id="inicio"
                    style={{
                        position: 'relative', overflow: 'hidden',
                        background: 'linear-gradient(120deg, #F7FAFF 0%, #EDF3FC 55%, #F9F1F1 100%)',
                        borderBottom: '1px solid #E5EBF5',
                    }}
                >
                    <svg
                        viewBox="0 0 1440 700" preserveAspectRatio="xMidYMid slice" aria-hidden="true"
                        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.55, pointerEvents: 'none' }}
                    >
                        <g stroke="#B9C8E2" strokeWidth="1" fill="none">
                            <path d="M60 120 L210 210 L120 360 L60 120 M210 210 L390 150 M120 360 L280 470 L430 400 M390 150 L520 260 L430 400 M1320 90 L1240 200 L1380 250 M1240 200 L1100 320 L1180 460 M1100 320 L960 250 M1180 460 L1330 520" />
                        </g>
                        <g fill="#9FB4D6">
                            <circle cx="60" cy="120" r="7" /><circle cx="210" cy="210" r="10" fill="#3B5FA0" />
                            <circle cx="120" cy="360" r="13" fill="#D89A97" /><circle cx="390" cy="150" r="6" />
                            <circle cx="280" cy="470" r="9" fill="#C9D6EB" /><circle cx="520" cy="260" r="7" fill={ROJO} opacity="0.5" />
                            <circle cx="430" cy="400" r="11" fill="#4E6FAC" opacity="0.5" /><circle cx="1320" cy="90" r="8" />
                            <circle cx="1240" cy="200" r="12" fill="#C9D6EB" /><circle cx="1380" cy="250" r="6" fill={ROJO} opacity="0.45" />
                            <circle cx="1100" cy="320" r="10" fill="#3B5FA0" /><circle cx="1180" cy="460" r="14" fill="#E3CDCC" />
                            <circle cx="960" cy="250" r="6" /><circle cx="1330" cy="520" r="9" fill="#C9D6EB" />
                        </g>
                    </svg>

                    <div
                        className="landing-hero-grid landing-section"
                        style={{
                            position: 'relative', display: 'grid', gridTemplateColumns: '1.08fr 0.92fr',
                            gap: 56, alignItems: 'center', padding: '92px 48px 96px',
                        }}
                    >
                        <div>
                            <div style={{
                                display: 'inline-flex', alignItems: 'center', gap: 9, background: '#ffffff',
                                border: '1px solid #DCE5F3', borderRadius: 999, padding: '7px 15px 7px 11px',
                                fontFamily: 'Poppins, sans-serif', fontSize: 11.5, fontWeight: 500,
                                letterSpacing: '0.06em', color: '#33456B', boxShadow: '0 2px 8px rgba(11,37,69,0.05)',
                            }}>
                                <span style={{ width: 7, height: 7, borderRadius: '50%', background: ROJO }} />
                                GOBERNANZA CIUDADANA EN CADENA · CONTENIDO DE EJEMPLO
                            </div>

                            <h1
                                className="landing-hero-title"
                                style={{
                                    fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 54, lineHeight: 1.08,
                                    letterSpacing: '-0.02em', color: AZUL, textTransform: 'uppercase', margin: '22px 0 0',
                                }}
                            >
                                Empoderando a Chile con gobernanza descentralizada y transparente
                            </h1>

                            <p style={{ fontSize: 18.5, lineHeight: 1.6, color: '#46536E', maxWidth: 560, margin: '22px 0 0' }}>
                                La primera DAO Ciudadana, construida para y por todos los chilenos.
                                Tu voz, tu decisión, tu país.
                            </p>

                            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 34, flexWrap: 'wrap' }}>
                                <button
                                    type="button"
                                    onClick={irAUnirse}
                                    className="landing-btn-red"
                                    style={{
                                        display: 'inline-flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                                        border: 'none', fontFamily: 'Poppins, sans-serif', fontSize: 13.5, fontWeight: 600,
                                        letterSpacing: '0.08em', padding: '16px 28px', borderRadius: 999,
                                        boxShadow: '0 8px 20px rgba(203,44,39,0.26)',
                                    }}
                                >
                                    ÚNETE A LA RED <i className="ph-bold ph-arrow-right" style={{ fontSize: 15 }} />
                                </button>
                                <a
                                    href="#como"
                                    className="landing-btn-ghost"
                                    style={{
                                        display: 'inline-flex', alignItems: 'center', gap: 9,
                                        fontFamily: 'Poppins, sans-serif', fontSize: 13.5, fontWeight: 600,
                                        letterSpacing: '0.08em', padding: '15px 24px', borderRadius: 999,
                                    }}
                                >
                                    <i className="ph-bold ph-play-circle" style={{ fontSize: 17 }} /> CÓMO FUNCIONA
                                </a>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 30, fontSize: 13.5, color: '#6B7894' }}>
                                <i className="ph-bold ph-shield-check" style={{ fontSize: 17, color: AZUL }} />
                                Identidad verificada con Cédula chilena · una persona, un voto
                            </div>
                        </div>

                        {/* Tarjeta de votación en vivo (demostrativa) */}
                        <div
                            className="landing-float"
                            style={{
                                background: '#ffffff', border: '1px solid #E2E9F4', borderRadius: 18,
                                boxShadow: '0 20px 44px rgba(11,37,69,0.10)', padding: 24,
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                                <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 12, fontWeight: 600, letterSpacing: '0.12em', color: '#6B7894' }}>
                                    VOTACIÓN DE MUESTRA
                                </div>
                                <div style={{
                                    display: 'inline-flex', alignItems: 'center', gap: 6, background: '#FBEAE8',
                                    color: '#A9211D', fontFamily: 'Poppins, sans-serif', fontSize: 11, fontWeight: 600,
                                    letterSpacing: '0.06em', padding: '5px 10px', borderRadius: 999,
                                }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: ROJO }} />
                                    EJEMPLO
                                </div>
                            </div>

                            <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 21, fontWeight: 600, color: TINTA, marginTop: 14, lineHeight: 1.3 }}>
                                Fondo comunal de ciclovías para Ñuñoa
                            </div>
                            <div style={{ fontSize: 13.5, color: '#6B7894', marginTop: 6 }}>
                                Propuesta #087 · cierra en 2 días 14 h
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 22 }}>
                                {[
                                    { label: 'A favor', pct: forPct, color: AZUL },
                                    { label: 'En contra', pct: 100 - forPct, color: ROJO },
                                ].map((b) => (
                                    <div key={b.label}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 600, color: TINTA, marginBottom: 7 }}>
                                            <span>{b.label}</span><span>{b.pct}%</span>
                                        </div>
                                        <div style={{ height: 9, borderRadius: 999, background: '#EDF1F8', overflow: 'hidden' }}>
                                            <div style={{ height: '100%', borderRadius: 999, background: b.color, transition: 'width .5s ease', width: `${b.pct}%` }} />
                                        </div>
                                    </div>
                                ))}
                            </div>

                            <div style={{ display: 'flex', gap: 10, marginTop: 22 }}>
                                <button
                                    type="button"
                                    onClick={() => { setForPct((v) => Math.min(96, v + 1)); setVotos((v) => v + 1); }}
                                    className="landing-btn-primary"
                                    style={{
                                        flex: 1, cursor: 'pointer', fontFamily: 'Poppins, sans-serif', fontSize: 13,
                                        fontWeight: 600, letterSpacing: '0.04em', padding: '13px 10px',
                                        borderRadius: 10, border: `1.5px solid ${AZUL}`,
                                    }}
                                >
                                    Apruebo
                                </button>
                                <button
                                    type="button"
                                    onClick={() => { setForPct((v) => Math.max(6, v - 1)); setVotos((v) => v + 1); }}
                                    style={{
                                        flex: 1, cursor: 'pointer', fontFamily: 'Poppins, sans-serif', fontSize: 13,
                                        fontWeight: 600, letterSpacing: '0.04em', padding: '13px 10px',
                                        borderRadius: 10, border: '1.5px solid #E0C6C4', background: '#ffffff', color: '#A9211D',
                                    }}
                                >
                                    Rechazo
                                </button>
                            </div>

                            <div style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 18,
                                paddingTop: 16, borderTop: '1px solid #EDF1F8', fontSize: 12.5, color: '#6B7894',
                            }}>
                                <span><strong style={{ color: TINTA, fontWeight: 600 }}>{votos.toLocaleString('es-CL')}</strong> votos emitidos</span>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                                    <i className="ph ph-link-simple" style={{ fontSize: 14 }} /> demostración
                                </span>
                            </div>
                        </div>
                    </div>
                </section>

                {/* ===== Banda de cifras (datos reales de la API) ===== */}
                <section className="landing-section" style={{ background: AZUL, color: '#ffffff', padding: '38px 48px' }}>
                    <div className="landing-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 24 }}>
                        {kpis.map((k) => (
                            <div key={k.etiqueta} style={{ borderLeft: '2px solid rgba(255,255,255,0.28)', paddingLeft: 18 }}>
                                <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 34, fontWeight: 600, letterSpacing: '-0.01em' }}>
                                    {k.valor}
                                </div>
                                <div style={{ fontSize: 13, color: '#C3D3EE', marginTop: 4 }}>{k.etiqueta}</div>
                            </div>
                        ))}
                    </div>
                    <div style={{ fontSize: 11.5, color: '#9DB6E0', marginTop: 18 }}>
                        Cifras leídas en vivo desde la red. “—” significa que el dato aún no está disponible.
                    </div>
                </section>

                {/* ===== Qué es ===== */}
                <section className="landing-section" style={{ padding: '84px 48px 76px' }}>
                    <div style={{ maxWidth: 620 }}>
                        <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 12, fontWeight: 600, letterSpacing: '0.16em', color: ROJO }}>
                            LA RED
                        </div>
                        <h2 className="landing-h2" style={{ fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 38, lineHeight: 1.15, letterSpacing: '-0.02em', color: AZUL, margin: '12px 0 0' }}>
                            ¿Qué es DAO-Ciudadano?
                        </h2>
                        <p style={{ fontSize: 17, lineHeight: 1.6, color: '#46536E', margin: '14px 0 0' }}>
                            Una organización que pertenece a sus miembros: las decisiones se proponen, se debaten
                            y se ejecutan sin intermediarios, con registro público de cada paso.
                        </p>
                    </div>

                    <div className="landing-grid-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 22, marginTop: 44 }}>
                        {PILARES.map((p) => (
                            <div key={p.title} className="landing-card" style={{ background: '#ffffff', border: '1px solid #E2E9F4', borderRadius: 16, padding: 28 }}>
                                <div style={{ width: 52, height: 52, borderRadius: 14, background: p.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', color: p.fg }}>
                                    <i className={`ph-bold ${p.icon}`} style={{ fontSize: 26 }} />
                                </div>
                                <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 20, fontWeight: 600, color: TINTA, marginTop: 20 }}>
                                    {p.title}
                                </div>
                                <p style={{ fontSize: 15, lineHeight: 1.62, color: '#5C6884', margin: '9px 0 0' }}>{p.desc}</p>
                            </div>
                        ))}
                    </div>
                </section>

                {/* ===== Cómo funciona ===== */}
                <section
                    id="como"
                    className="landing-section"
                    style={{ position: 'relative', overflow: 'hidden', background: '#F6F9FE', borderTop: '1px solid #E5EBF5', borderBottom: '1px solid #E5EBF5', padding: '80px 48px' }}
                >
                    <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 12, fontWeight: 600, letterSpacing: '0.16em', color: ROJO }}>
                        EL PROCESO
                    </div>
                    <h2 className="landing-h2" style={{ fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 38, lineHeight: 1.15, letterSpacing: '-0.02em', color: AZUL, margin: '12px 0 0' }}>
                        Cómo funciona
                    </h2>

                    <div style={{ position: 'relative', marginTop: 52 }}>
                        <div
                            aria-hidden="true"
                            className="landing-steps-line"
                            style={{ position: 'absolute', top: 44, left: '12.5%', width: '75%', height: 0, borderTop: '2px dashed #C6D5EC', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                        >
                            {['#003897', '#7E95BF', '#D9908C', '#CB2C27'].map((c, i) => (
                                <span key={i} style={{ width: 10, height: 10, borderRadius: '50%', background: c }} />
                            ))}
                        </div>

                        <div className="landing-grid-4" style={{ position: 'relative', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 24 }}>
                            {PASOS.map((s) => (
                                <div key={s.n} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 14 }}>
                                    <div style={{
                                        width: 88, height: 88, borderRadius: '50%', background: '#ffffff',
                                        border: '1px solid #DCE5F3', boxShadow: '0 8px 20px rgba(11,37,69,0.07)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        color: s.color, position: 'relative',
                                    }}>
                                        <i className={`ph ${s.icon}`} style={{ fontSize: 34 }} />
                                        <span style={{
                                            position: 'absolute', top: -6, right: -6, width: 28, height: 28, borderRadius: '50%',
                                            background: s.color, color: '#ffffff', fontFamily: 'Poppins, sans-serif',
                                            fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        }}>
                                            {s.n}
                                        </span>
                                    </div>
                                    <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 18, fontWeight: 600, color: TINTA }}>{s.title}</div>
                                    <p style={{ fontSize: 14.5, lineHeight: 1.6, color: '#5C6884', margin: 0, maxWidth: 240 }}>{s.desc}</p>
                                </div>
                            ))}
                        </div>
                    </div>
                </section>

                {/* ===== Propuestas ===== */}
                <section id="propuestas" className="landing-section" style={{ padding: '82px 48px 78px' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 32, flexWrap: 'wrap' }}>
                        <div style={{ maxWidth: 560 }}>
                            <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 12, fontWeight: 600, letterSpacing: '0.16em', color: ROJO }}>
                                PARTICIPA HOY
                            </div>
                            <h2 className="landing-h2" style={{ fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 38, lineHeight: 1.15, letterSpacing: '-0.02em', color: AZUL, margin: '12px 0 0' }}>
                                Propuestas destacadas
                            </h2>
                            <p style={{ fontSize: 13.5, color: '#8090AD', margin: '10px 0 0' }}>
                                Ejemplos ilustrativos del formato de propuesta. Las propuestas reales viven
                                en el panel ciudadano.
                            </p>
                        </div>

                        <div style={{ display: 'flex', gap: 8 }}>
                            {FILTROS.map((label) => {
                                const activo = label === filtro;
                                return (
                                    <button
                                        key={label}
                                        type="button"
                                        onClick={() => setFiltro(label)}
                                        style={{
                                            cursor: 'pointer', fontFamily: 'Poppins, sans-serif', fontSize: 12.5,
                                            fontWeight: 600, letterSpacing: '0.05em', padding: '10px 18px',
                                            borderRadius: 999,
                                            border: `1.5px solid ${activo ? AZUL : '#D7E1F1'}`,
                                            background: activo ? AZUL : '#ffffff',
                                            color: activo ? '#ffffff' : '#33456B',
                                        }}
                                    >
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div className="landing-grid-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 22, marginTop: 34 }}>
                        {mostradas.map((p) => (
                            <div key={p.code} className="landing-card" style={{ display: 'flex', flexDirection: 'column', background: '#ffffff', border: '1px solid #E2E9F4', borderRadius: 16, padding: 24 }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                                    <span style={{
                                        display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'Poppins, sans-serif',
                                        fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', padding: '6px 11px',
                                        borderRadius: 999, background: p.tagBg, color: p.tagFg,
                                    }}>
                                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: p.tagDot }} />
                                        {p.status}
                                    </span>
                                    <span style={{ fontSize: 12, color: '#94A2BC', fontFamily: 'Poppins, sans-serif' }}>{p.code}</span>
                                </div>

                                <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 20, fontWeight: 600, lineHeight: 1.3, color: TINTA, marginTop: 16 }}>
                                    {p.title}
                                </div>
                                <p style={{ fontSize: 14.5, lineHeight: 1.6, color: '#5C6884', margin: '9px 0 0' }}>{p.desc}</p>

                                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 20, padding: '12px 14px', background: '#F6F9FE', border: '1px solid #E7EDF7', borderRadius: 12 }}>
                                    <svg viewBox="0 0 14 60" aria-hidden="true" style={{ width: 14, height: 58, flexShrink: 0 }}>
                                        <line x1="7" y1="2" x2="7" y2="58" stroke="#C6D5EC" strokeWidth="2" strokeDasharray="2 5" />
                                        <circle cx="7" cy={p.mapY} r="5" fill={ROJO} />
                                    </svg>
                                    <div>
                                        <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 13.5, fontWeight: 600, color: TINTA }}>{p.place}</div>
                                        <div style={{ fontSize: 12.5, color: '#6B7894', marginTop: 2 }}>{p.region}</div>
                                    </div>
                                </div>

                                <div style={{ marginTop: 20 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: '#6B7894', marginBottom: 7 }}>
                                        <span>Participación</span>
                                        <span style={{ fontWeight: 600, color: TINTA }}>{p.pct}% del quórum</span>
                                    </div>
                                    <div style={{ height: 7, borderRadius: 999, background: '#EDF1F8', overflow: 'hidden' }}>
                                        <div style={{ height: '100%', borderRadius: 999, background: p.barColor, width: `${p.pct}%` }} />
                                    </div>
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 18, paddingTop: 16, borderTop: '1px solid #EDF1F8', fontSize: 12.5, color: '#6B7894' }}>
                                    <span>{p.meta}</span>
                                    <button
                                        type="button"
                                        onClick={() => navigate('/dashboard/propuestas')}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'Poppins, sans-serif', fontSize: 12.5, fontWeight: 600, color: AZUL, padding: 0 }}
                                    >
                                        Ver propuestas reales →
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>

                {/* ===== CTA comunidad ===== */}
                <section id="comunidad" className="landing-section" style={{ padding: '0 48px 84px' }}>
                    <div
                        className="landing-cta-grid"
                        style={{
                            display: 'grid', gridTemplateColumns: 'minmax(360px, 1fr) minmax(0, 0.9fr)', gap: 0,
                            background: 'linear-gradient(120deg, #F7FAFF 0%, #EDF3FC 60%, #F9F1F1 100%)',
                            border: '1px solid #E2E9F4', borderRadius: 22, overflow: 'hidden',
                        }}
                    >
                        <div style={{ padding: '52px 48px' }}>
                            <h2 className="landing-h2" style={{ fontFamily: 'Poppins, sans-serif', fontWeight: 600, fontSize: 34, lineHeight: 1.18, letterSpacing: '-0.02em', color: AZUL, margin: 0, maxWidth: 460 }}>
                                Súmate a la red ciudadana
                            </h2>
                            <p style={{ fontSize: 16.5, lineHeight: 1.62, color: '#46536E', margin: '14px 0 0', maxWidth: 460 }}>
                                Verifica tu identidad una sola vez con tu Cédula y participa en cada votación
                                desde tu teléfono.
                            </p>
                            <div style={{ display: 'flex', gap: 12, marginTop: 28, flexWrap: 'wrap' }}>
                                <button
                                    type="button"
                                    onClick={irAUnirse}
                                    className="landing-btn-primary"
                                    style={{
                                        cursor: 'pointer', border: 'none', fontFamily: 'Poppins, sans-serif',
                                        fontSize: 13.5, fontWeight: 600, letterSpacing: '0.08em',
                                        padding: '16px 28px', borderRadius: 999, boxShadow: '0 8px 20px rgba(0,56,151,0.22)',
                                    }}
                                >
                                    ÚNETE A LA RED
                                </button>
                                <button
                                    type="button"
                                    onClick={() => navigate('/dashboard')}
                                    className="landing-btn-ghost"
                                    style={{
                                        cursor: 'pointer', fontFamily: 'Poppins, sans-serif', fontSize: 13.5,
                                        fontWeight: 600, letterSpacing: '0.08em', padding: '15px 26px', borderRadius: 999,
                                    }}
                                >
                                    VER EL PANEL CIUDADANO
                                </button>
                            </div>
                        </div>

                        <div style={{ position: 'relative', minHeight: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.45)' }}>
                            <img
                                src="/assets/logo-lockup.png"
                                alt="EstamosDAO Chile"
                                style={{ maxWidth: '72%', maxHeight: 260, objectFit: 'contain', display: 'block' }}
                            />
                        </div>
                    </div>
                </section>

                {/* ===== Footer ===== */}
                <footer className="landing-section" style={{ background: TINTA, color: '#C3D3EE', padding: '56px 48px 30px' }}>
                    <div className="landing-footer-grid" style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr 1fr 1fr', gap: 36 }}>
                        <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                <img
                                    src="/assets/logo-mark.png"
                                    alt="EstamosDAO Chile"
                                    style={{ width: 46, height: 46, objectFit: 'contain', background: '#ffffff', borderRadius: 10, padding: 3, display: 'block' }}
                                />
                                <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1 }}>
                                    <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 20, color: '#ffffff' }}>
                                        Estamos<span style={{ fontWeight: 700 }}>DAO</span>
                                    </span>
                                    <span style={{ fontFamily: 'Poppins, sans-serif', fontSize: 10, fontWeight: 500, letterSpacing: '0.28em', color: '#8FA6CB', marginTop: 3 }}>
                                        CHILE
                                    </span>
                                </span>
                            </div>
                            <p style={{ fontSize: 14, lineHeight: 1.6, color: '#93A8CC', margin: '18px 0 0', maxWidth: 300 }}>
                                Construyendo juntos el futuro de nuestra nación.
                            </p>
                        </div>

                        <div>
                            <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 11.5, fontWeight: 600, letterSpacing: '0.14em', color: '#ffffff' }}>
                                CONTACTO
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginTop: 16, fontSize: 14 }}>
                                <span style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                                    <i className="ph ph-envelope-simple" style={{ fontSize: 15 }} /> hola@estamosdao.cl
                                </span>
                                <span style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                                    <i className="ph ph-globe-simple" style={{ fontSize: 15 }} /> estamosdao.cl
                                </span>
                            </div>
                        </div>

                        <div>
                            <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 11.5, fontWeight: 600, letterSpacing: '0.14em', color: '#ffffff' }}>
                                LA RED
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginTop: 16, fontSize: 14 }}>
                                <a href="#propuestas" className="landing-footer-link">Propuestas</a>
                                <a href="#como" className="landing-footer-link">Cómo funciona</a>
                                <a href="#comunidad" className="landing-footer-link">Comunidad</a>
                            </div>
                        </div>

                        <div>
                            <div style={{ fontFamily: 'Poppins, sans-serif', fontSize: 11.5, fontWeight: 600, letterSpacing: '0.14em', color: '#ffffff' }}>
                                LEGAL
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginTop: 16, fontSize: 14 }}>
                                <a href="#inicio" className="landing-footer-link">Términos de uso</a>
                                <a href="#inicio" className="landing-footer-link">Privacidad de datos</a>
                                <a href="#inicio" className="landing-footer-link">Estatutos de la DAO</a>
                            </div>
                        </div>
                    </div>

                    <div style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap',
                        marginTop: 40, paddingTop: 22, borderTop: '1px solid rgba(255,255,255,0.14)', fontSize: 13, color: '#8FA6CB',
                    }}>
                        <span>
                            <strong style={{ color: '#ffffff', fontWeight: 600 }}>EstamosDAO Chile:</strong>{' '}
                            Construyendo juntos el futuro de nuestra nación.
                        </span>
                        <span>© {new Date().getFullYear()} EstamosDAO</span>
                    </div>
                </footer>
            </div>
        </div>
    );
};

export default LandingPage;
