/* eslint-disable */
// ewash — main tabs: Home, Bookings, Services, Profile + Support

const { useState: useS_h, useEffect: useE_h, useMemo: useM_h, useRef: useR_h } = React;

// Smoothly count from 0 to `target` over `duration` ms (ease-out cubic).
// Respects prefers-reduced-motion.
function useCountUp(target, duration = 1200) {
  const [value, setValue] = useS_h(0);
  useE_h(() => {
    if (typeof window === 'undefined') { setValue(target); return; }
    const reduced = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { setValue(target); return; }
    let raf, start;
    const tick = (ts) => {
      if (start == null) start = ts;
      const t = Math.min(1, (ts - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

// ─────────────────────────────────────────────────────────────
// HOME
// ─────────────────────────────────────────────────────────────
function HomeScreen({ t, lang, openBooking, gotoSupport, gotoTariffs, theme, variant, profile }) {
  const litersSaved = 2147;
  const litersCount = useCountUp(litersSaved, 1400);
  const washCount = useCountUp(23, 900);
  return (
    <div className="app-scroll">
      <div className="appbar">
        <div className="row gap-10">
          <Icons.Logo size={30} style={{ color: 'var(--primary)' }} />
          <div className="col" style={{ gap: 2 }}>
            <div className="t-tiny" style={{ color: 'var(--text-2)', fontWeight: 600 }}>
              {t.welcome},
            </div>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15, lineHeight: 1 }}>
              {profile.name}
            </div>
          </div>
        </div>
        <div className="row gap-4">
          <button className="icon-btn" aria-label="notifications">
            <div style={{ position: 'relative' }}>
              <Icons.Bell size={22} />
              <span style={{
                position: 'absolute', top: -2, right: -2,
                width: 9, height: 9, borderRadius: 99,
                background: 'var(--accent)', border: '2px solid var(--bg)',
                boxShadow: '0 0 0 0 color-mix(in srgb, var(--accent) 70%, transparent)',
                animation: 'dotPulse 2.4s ease-out infinite',
              }}/>
            </div>
          </button>
        </div>
      </div>

      <div className="px-16 col gap-20 anim-stagger" style={{ paddingBottom: 24 }}>
        {/* HERO */}
        <div className="hero">
          <div className="row gap-8" style={{ position: 'relative', zIndex: 1, marginBottom: 12 }}>
            <span className="chip" style={{
              background: 'rgba(255,255,255,0.14)',
              color: '#fff', border: '1px solid rgba(255,255,255,0.18)',
            }}>
              <Icons.Leaf size={13}/> Sans eau · 100%
            </span>
          </div>
          <div style={{
            fontFamily: 'var(--font-display)', fontWeight: 800,
            fontSize: 28, lineHeight: 1.05, color: '#fff',
            marginBottom: 10, position: 'relative', zIndex: 1,
            letterSpacing: '-0.02em', maxWidth: 240,
          }}>
            {lang === 'ar' ? 'سيارة نظيفة، بدون قطرة ماء.' : 'Voiture propre,\nzéro goutte d’eau.'}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.78)', fontSize: 13.5, marginBottom: 18, position: 'relative', zIndex: 1, maxWidth: 250 }}>
            {t.tagline} · Casablanca
          </div>
          <button onClick={openBooking}
            className="press"
            style={{
              background: variant === 'premium' ? 'var(--gold)' : '#fff',
              color: variant === 'premium' ? '#0a0a0a' : 'var(--primary)',
              border: 'none', borderRadius: 999,
              padding: '14px 24px', fontWeight: 700, fontSize: 15,
              letterSpacing: '-0.01em',
              display: 'inline-flex', alignItems: 'center', gap: 8,
              position: 'relative', zIndex: 1, cursor: 'pointer',
              boxShadow: '0 8px 22px -8px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.6)',
            }}>
            {t.bookCta}
            <Icons.ChevronRight size={18} stroke={2.5} />
          </button>
          {/* drop decoration */}
          <svg className="water-glyph" viewBox="0 0 100 105">
            <path d="M50 4 C68 24, 88 44, 88 64 a38 38 0 0 1-76 0 C12 44, 32 24, 50 4z"
              fill="none" stroke="#fff" strokeWidth="2"/>
          </svg>
        </div>

        {/* QUICK STATS */}
        <div className="row gap-10">
          <div className="card" style={{ flex: 1, padding: 14, borderRadius: 18 }}>
            <div className="row gap-6 mb-8">
              <Icons.Drop size={16} style={{ color: 'var(--primary)' }} />
              <span className="t-tiny" style={{ color: 'var(--text-2)', fontWeight: 600 }}>{t.waterSaved}</span>
            </div>
            <div className="t-num" style={{ fontWeight: 800, fontSize: 26, color: 'var(--text)' }}>
              {litersCount.toLocaleString('fr-FR')}<span style={{ fontSize: 14, color: 'var(--text-2)', marginInlineStart: 4 }}>L</span>
            </div>
          </div>
          <div className="card" style={{ flex: 1, padding: 14, borderRadius: 18 }}>
            <div className="row gap-6 mb-8">
              <Icons.Sparkle size={16} style={{ color: 'var(--accent)' }} />
              <span className="t-tiny" style={{ color: 'var(--text-2)', fontWeight: 600 }}>Lavages</span>
            </div>
            <div className="t-num" style={{ fontWeight: 800, fontSize: 26, color: 'var(--text)' }}>
              {washCount}
            </div>
          </div>
        </div>

        {/* NEXT APPOINTMENT */}
        <div>
          <div className="row between" style={{ marginBottom: 10 }}>
            <div className="t-h3">{t.nextAppointment}</div>
            <span className="chip chip-accent">
              <span className="live-dot" />
              {t.upcoming}
            </span>
          </div>
          <div className="card card-elev" style={{ padding: 16 }}>
            <div className="row gap-12">
              <div style={{
                width: 56, minWidth: 56,
                borderRadius: 14, padding: '10px 0',
                background: 'var(--primary-soft)',
                color: 'var(--primary-soft-text)',
                textAlign: 'center',
                boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.5), 0 6px 14px -8px color-mix(in srgb, var(--primary) 35%, transparent)',
              }}>
                <div className="t-tiny" style={{ fontWeight: 700, opacity: 0.85, letterSpacing: '0.12em' }}>SAM</div>
                <div className="t-num" style={{ fontWeight: 800, fontSize: 22, lineHeight: 1, letterSpacing: '-0.02em' }}>16</div>
                <div className="t-tiny" style={{ opacity: 0.85, letterSpacing: '0.08em' }}>MAI</div>
              </div>
              <div className="col gap-4 flex-1">
                <div style={{ fontWeight: 700, fontSize: 15 }}>Le Complet · Berline</div>
                <div className="t-muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icons.Clock size={13}/> 10:30 · 45 {t.min}
                </div>
                <div className="t-muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icons.Pin size={13}/> Bd Anfa, Casablanca
                </div>
              </div>
            </div>
            <div className="row gap-8 mt-12">
              <Btn variant="soft" style={{ flex: 1 }}>{t.track}</Btn>
              <button className="btn btn-secondary" style={{ flex: '0 0 auto' }}>
                <Icons.Edit size={16}/>
              </button>
            </div>
          </div>
        </div>

        {/* QUICK ACTIONS */}
        <div>
          <div className="t-h3 mb-12">{t.quickActions}</div>
          <div className="row gap-10">
            <button onClick={gotoTariffs} className="card press" style={{
              flex: 1, padding: 14, borderRadius: 18, textAlign: 'inherit',
              display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start',
              cursor: 'pointer',
            }}>
              <div style={{
                width: 38, height: 38, borderRadius: 12,
                background: 'var(--accent-soft)', color: 'var(--accent-soft-text)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.5)',
              }}><Icons.Tag size={18}/></div>
              <div style={{ fontWeight: 700, fontSize: 13.5, letterSpacing: '-0.005em' }}>{t.viewTariffs}</div>
            </button>
            <button onClick={gotoSupport} className="card press" style={{
              flex: 1, padding: 14, borderRadius: 18, textAlign: 'inherit',
              display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start',
              cursor: 'pointer',
            }}>
              <div style={{
                width: 38, height: 38, borderRadius: 12,
                background: 'var(--primary-soft)', color: 'var(--primary-soft-text)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.5)',
              }}><Icons.Message size={18}/></div>
              <div style={{ fontWeight: 700, fontSize: 13.5, letterSpacing: '-0.005em' }}>{t.talkTeam}</div>
            </button>
          </div>
        </div>

        {/* PROMISE */}
        <div className="card card-soft" style={{
          background: 'var(--surface-2)', padding: 16, borderRadius: 20,
        }}>
          <div className="row gap-10 mb-8">
            <div style={{
              width: 32, height: 32, borderRadius: 10,
              background: variant === 'premium' ? 'var(--accent)' : 'var(--accent)',
              color: '#0a1a0a',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}><Icons.Shield size={17}/></div>
            <div style={{ fontWeight: 700, fontSize: 14 }}>{t.ourPromise}</div>
          </div>
          <div className="t-muted">{t.promiseBody}</div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// BOOKINGS HISTORY
// ─────────────────────────────────────────────────────────────
function BookingsScreen({ t, lang, openBooking, theme }) {
  const [tab, setTab] = useS_h('upcoming');
  const items = {
    upcoming: [
      { date: '16 mai', time: '10:30', service: 'Le Complet', cat: 'Berline', loc: 'Bd Anfa, Casablanca', status: 'upcoming', ref: 'EW-2026-0419' },
      { date: '23 mai', time: '15:00', service: "L'Extérieur", cat: 'Berline', loc: 'Stand Bouskoura', status: 'upcoming', ref: 'EW-2026-0421' },
    ],
    past: [
      { date: '02 mai', time: '11:00', service: 'Céramique', cat: 'Berline', loc: 'Bd Anfa', status: 'completed', ref: 'EW-2026-0399', rating: 5 },
      { date: '18 avr', time: '09:30', service: 'Polissage', cat: 'Berline', loc: 'Bd Anfa', status: 'completed', ref: 'EW-2026-0381', rating: 5 },
      { date: '04 avr', time: '14:00', service: 'Le Complet', cat: 'Berline', loc: 'Stand Bouskoura', status: 'cancelled', ref: 'EW-2026-0362' },
    ],
  };
  return (
    <div className="app-scroll">
      <TopBar title={t.bookings} right={<button className="icon-btn"><Icons.Search size={20}/></button>}/>
      <div className="px-16 col gap-16 anim-stagger" style={{ paddingBottom: 24 }}>
        <div className="row" style={{
          background: 'var(--surface-2)',
          borderRadius: 999, padding: 4,
        }}>
          {['upcoming', 'past'].map(k => (
            <button key={k} onClick={() => setTab(k)} style={{
              flex: 1, padding: '11px 16px', borderRadius: 999,
              background: tab === k ? 'var(--surface)' : 'transparent',
              color: tab === k ? 'var(--text)' : 'var(--text-2)',
              fontWeight: tab === k ? 700 : 600, fontSize: 13.5,
              letterSpacing: '-0.005em',
              boxShadow: tab === k
                ? '0 1px 2px rgba(14,42,42,0.05), 0 4px 8px -2px rgba(14,42,42,0.06)'
                : 'none',
              transition: 'background 0.22s var(--ease-soft), color 0.22s var(--ease-soft), box-shadow 0.22s var(--ease-soft), font-weight 0.18s',
            }}>{t[k]}</button>
          ))}
        </div>

        {items[tab].length === 0 && (
          <div className="card center" style={{
            padding: '36px 24px', flexDirection: 'column', gap: 12,
            background: 'var(--surface-2)', border: 'none',
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: 18,
              background: 'var(--surface)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--text-3)',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.5), 0 4px 12px -4px rgba(14,42,42,0.08)',
            }}>
              <Icons.Calendar size={26}/>
            </div>
            <div className="col gap-4" style={{ alignItems: 'center', textAlign: 'center' }}>
              <div style={{ fontWeight: 700, fontSize: 14.5 }}>Aucune réservation</div>
              <div className="t-muted" style={{ fontSize: 13 }}>Vos rendez-vous apparaîtront ici</div>
            </div>
            <Btn variant="soft" onClick={openBooking} style={{ marginTop: 4 }}>
              {t.bookCta}
            </Btn>
          </div>
        )}

        {items[tab].map((b, i) => (
          <div key={i} className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="row gap-12" style={{ padding: 16 }}>
              <div style={{
                width: 50, minWidth: 50,
                borderRadius: 12,
                background: 'var(--surface-2)',
                color: 'var(--text)',
                textAlign: 'center',
                padding: '8px 0',
              }}>
                <div className="t-num" style={{ fontWeight: 800, fontSize: 18, lineHeight: 1.1 }}>{b.date.split(' ')[0]}</div>
                <div className="t-tiny" style={{ letterSpacing: '0.1em', textTransform: 'uppercase' }}>{b.date.split(' ')[1]}</div>
              </div>
              <div className="col gap-4 flex-1" style={{ minWidth: 0 }}>
                <div className="row between">
                  <div style={{ fontWeight: 700, fontSize: 14.5 }}>{b.service}</div>
                  {b.status === 'upcoming' && <span className="chip chip-accent" style={{ fontSize: 10.5, padding: '3px 8px' }}>{t.upcoming}</span>}
                  {b.status === 'completed' && <span className="chip" style={{ fontSize: 10.5, padding: '3px 8px' }}>{t.completed}</span>}
                  {b.status === 'cancelled' && <span className="chip" style={{ fontSize: 10.5, padding: '3px 8px', color: 'var(--danger)', borderColor: 'var(--danger)' }}>{t.cancelled}</span>}
                </div>
                <div className="t-muted" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <Icons.Clock size={12}/> {b.time} · {b.cat}
                </div>
                <div className="t-muted" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <Icons.Pin size={12}/> {b.loc}
                </div>
                {b.rating && (
                  <div className="row gap-2 mt-4">
                    {Array.from({ length: 5 }).map((_, j) => (
                      <Icons.Star key={j} size={12} style={{ color: j < b.rating ? 'var(--accent)' : 'var(--border-strong)' }}/>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {b.status === 'upcoming' && (
              <div className="row" style={{ borderTop: '1px solid var(--border)' }}>
                <button style={{ flex: 1, padding: '12px 0', fontWeight: 600, fontSize: 13.5, color: 'var(--primary)' }}>{t.track}</button>
                <div style={{ width: 1, background: 'var(--border)' }} />
                <button style={{ flex: 1, padding: '12px 0', fontWeight: 600, fontSize: 13.5, color: 'var(--text-2)' }}>{t.edit}</button>
              </div>
            )}
            {b.status === 'completed' && (
              <div className="row" style={{ borderTop: '1px solid var(--border)' }}>
                <button style={{ flex: 1, padding: '12px 0', fontWeight: 600, fontSize: 13.5, color: 'var(--primary)' }} onClick={openBooking}>{t.rebook}</button>
                {!b.rating && <>
                  <div style={{ width: 1, background: 'var(--border)' }} />
                  <button style={{ flex: 1, padding: '12px 0', fontWeight: 600, fontSize: 13.5, color: 'var(--text-2)' }}>{t.leaveReview}</button>
                </>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SERVICES / TARIFFS
// ─────────────────────────────────────────────────────────────
const TARIFF_LAVAGE = [
  { name: "L'Extérieur", durationMin: 25, prices: { A: 60, B: 65, C: 70 },
    desc: 'Dégraissage carrosserie, vitres, jantes, cirage pneus + wax hydrophobe 1 semaine' },
  { name: 'Le Complet', durationMin: 45, prices: { A: 115, B: 125, C: 135 },
    desc: "L'Extérieur + rénovation intérieure, tableau de bord, aspiration tapis & sièges + anti-statique", popular: true },
  { name: 'Le Salon', durationMin: 150, prices: { A: 490, B: 540, C: 590 },
    desc: 'Le Complet + injection/extraction sièges, tissus, plafond, moquette + pinceau aérations' },
];
const TARIFF_ESTHETIQUE = [
  { name: 'Le Polissage', durationMin: 180, prices: { A: 990, B: 1070, C: 1150 },
    desc: 'Carrosserie comme neuve · élimine micro-rayures, traces, oxydation + lustrage & protection hydrophobe 4 semaines', popular: true },
  { name: 'Céramique 6 mois', durationMin: 240, prices: { A: 800, B: 800, C: 800 },
    desc: 'En complément du Polissage · protection hydrophobe, anti-UV, anti-poussière' },
  { name: 'Céramique 6 semaines', durationMin: 90, prices: { A: 200, B: 200, C: 200 },
    desc: 'Protection courte durée' },
  { name: 'Lustrage', durationMin: 60, prices: { A: 600, B: 650, C: 700 },
    desc: 'Brillance éclatante + protection légère' },
  { name: 'Rénovation cuir', durationMin: 60, prices: { A: 250, B: 250, C: 250 },
    desc: 'Sièges en cuir nettoyés et nourris' },
  { name: 'Rénovation plastiques 6 mois', durationMin: 45, prices: { A: 150, B: 200, C: 250 },
    desc: 'Pare-chocs, moulures, plastiques extérieurs · 6 mois' },
  { name: 'Rénovation optiques', durationMin: 45, prices: { A: 150, B: 150, C: 150 },
    desc: 'Phares retrouvent leur clarté' },
];

function ServicesScreen({ t, lang, openBooking, theme }) {
  const [tab, setTab] = useS_h('lavage');
  const items = tab === 'lavage' ? TARIFF_LAVAGE : TARIFF_ESTHETIQUE;
  return (
    <div className="app-scroll">
      <TopBar title={t.tariffs} />
      <div className="px-16 col gap-16 anim-stagger" style={{ paddingBottom: 24 }}>
        <div className="row" style={{ background: 'var(--surface-2)', borderRadius: 999, padding: 4 }}>
          {['lavage', 'esthetique'].map(k => (
            <button key={k} onClick={() => setTab(k)} style={{
              flex: 1, padding: '11px 16px', borderRadius: 999,
              background: tab === k ? 'var(--surface)' : 'transparent',
              color: tab === k ? 'var(--text)' : 'var(--text-2)',
              fontWeight: tab === k ? 700 : 600, fontSize: 13.5,
              letterSpacing: '-0.005em',
              boxShadow: tab === k
                ? '0 1px 2px rgba(14,42,42,0.05), 0 4px 8px -2px rgba(14,42,42,0.06)'
                : 'none',
              transition: 'background 0.22s var(--ease-soft), color 0.22s var(--ease-soft), box-shadow 0.22s var(--ease-soft)',
            }}>{t[k]}</button>
          ))}
        </div>

        <div className="card-soft" style={{
          padding: 14, borderRadius: 18,
          display: 'flex', gap: 10, alignItems: 'center',
        }}>
          <Icons.Leaf size={20} style={{ color: 'var(--accent)' }} />
          <div className="t-muted" style={{ flex: 1, fontSize: 12.5 }}>
            <strong style={{ color: 'var(--text)' }}>{t.ecoTag}</strong><br/>
            A : Citadine · B : Petite berline / SUV · C : Grande berline / SUV
          </div>
        </div>

        {items.map((s, i) => {
          const flat = s.prices.A === s.prices.B && s.prices.B === s.prices.C;
          return (
            <div key={i} className="card card-elev" style={{ padding: 16 }}>
              <div className="row between mb-8">
                <div className="col gap-4">
                  <div className="row gap-8">
                    <div style={{ fontWeight: 700, fontSize: 15.5 }}>{s.name}</div>
                    {s.popular && <span className="chip chip-primary" style={{ fontSize: 10.5, padding: '2px 8px' }}>★ {t.mostPopular}</span>}
                  </div>
                  <div className="t-muted">{s.desc}</div>
                </div>
              </div>
              <div className="row gap-6 mb-12">
                <span className="chip"><Icons.Clock size={12}/> {s.durationMin} {t.min}</span>
              </div>
              {flat ? (
                <div style={{
                  background: 'var(--surface-2)',
                  borderRadius: 12, padding: '12px 14px',
                  display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                  boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.4)',
                }}>
                  <span className="t-tiny" style={{ letterSpacing: '0.1em', fontWeight: 700, color: 'var(--text-2)' }}>
                    TOUTES CATÉGORIES
                  </span>
                  <span className="t-num" style={{ fontWeight: 800, fontSize: 22, color: 'var(--text)', letterSpacing: '-0.02em' }}>
                    {s.prices.A}<span style={{ fontSize: 12, color: 'var(--text-2)', marginInlineStart: 4 }}>DH</span>
                  </span>
                </div>
              ) : (
                <div className="row gap-8">
                  {['A', 'B', 'C'].map(c => (
                    <div key={c} className="flex-1" style={{
                      background: 'var(--surface-2)',
                      borderRadius: 12, padding: '10px 8px',
                      textAlign: 'center',
                      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.4)',
                    }}>
                      <div className="t-tiny" style={{ letterSpacing: '0.12em', fontWeight: 800, color: 'var(--text-3)' }}>{c}</div>
                      <div className="t-num" style={{ fontWeight: 800, fontSize: 17, color: 'var(--text)', marginTop: 2, letterSpacing: '-0.015em' }}>
                        {s.prices[c]}<span style={{ fontSize: 10, color: 'var(--text-2)', marginInlineStart: 2 }}>DH</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <Btn variant="soft" block style={{ marginTop: 12 }} onClick={openBooking}>
                {t.bookCta}
              </Btn>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// PROFILE
// ─────────────────────────────────────────────────────────────
function ProfileScreen({ t, lang, setLang, theme, setTheme, variant, setVariant, profile, onLogout }) {
  return (
    <div className="app-scroll">
      <TopBar title={t.myProfile} />
      <div className="px-16 col gap-20 anim-stagger" style={{ paddingBottom: 24 }}>
        {/* User card */}
        <div className="card card-elev" style={{ padding: 16, display: 'flex', gap: 14, alignItems: 'center' }}>
          <div style={{
            width: 60, height: 60, borderRadius: 18,
            background: 'linear-gradient(135deg, color-mix(in srgb, var(--primary) 92%, white) 0%, var(--primary) 50%, color-mix(in srgb, var(--primary) 70%, black) 100%)',
            color: 'var(--primary-text)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 26,
            letterSpacing: '-0.02em',
            boxShadow:
              'inset 0 1px 0 rgba(255,255,255,0.25), 0 8px 18px -8px color-mix(in srgb, var(--primary) 50%, transparent)',
          }}>{profile.name[0]}</div>
          <div className="col gap-2 flex-1">
            <div style={{ fontWeight: 700, fontSize: 16 }}>{profile.name}</div>
            <div className="t-muted">+212 {profile.phone}</div>
          </div>
          <button className="icon-btn"><Icons.Edit size={18}/></button>
        </div>

        {/* Eco impact card */}
        <div className="card-soft" style={{
          padding: '20px 18px', borderRadius: 22,
          background: 'var(--hero-grad)', color: '#fff',
          position: 'relative', overflow: 'hidden',
          boxShadow: '0 20px 40px -16px rgba(15,120,120,0.45)',
        }}>
          <div style={{
            position: 'absolute', insetInlineEnd: -30, top: -30,
            width: 160, height: 160, borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(255,255,255,0.16) 0%, transparent 65%)',
            pointerEvents: 'none',
          }}/>
          <div className="row gap-8 mb-8" style={{ position: 'relative' }}>
            <Icons.Drop size={18} />
            <div className="t-tiny" style={{ fontWeight: 700, letterSpacing: '0.12em', color: 'rgba(255,255,255,0.78)' }}>VOTRE IMPACT</div>
          </div>
          <div className="row" style={{ alignItems: 'baseline', gap: 8, position: 'relative' }}>
            <div style={{
              fontFamily: 'var(--font-display)', fontWeight: 800,
              fontSize: 40, letterSpacing: '-0.03em', lineHeight: 1.0,
              fontVariantNumeric: 'tabular-nums',
            }}>2 147<span style={{ fontSize: 22, marginInlineStart: 4, opacity: 0.85 }}>L</span></div>
          </div>
          <div className="t-muted" style={{ color: 'rgba(255,255,255,0.78)', marginTop: 6, position: 'relative' }}>
            {t.waterSaved.toLowerCase()} · soit {Math.round(2147 / 12)} douches évitées
          </div>
        </div>

        <ProfileSection title={lang === 'ar' ? 'حسابي' : 'Mon compte'}>
          <ProfileRow icon={<Icons.CarSide size={18}/>} label={t.myVehicles} value="2 véhicules" />
          <ProfileRow icon={<Icons.Pin size={18}/>} label={t.addresses} value="3" />
          <ProfileRow icon={<Icons.Wallet size={18}/>} label={t.paymentMethods} value={t.paymentNote} />
        </ProfileSection>

        <ProfileSection title={t.settings}>
          <ProfileRow icon={theme === 'dark' ? <Icons.Moon size={18}/> : <Icons.Sun size={18}/>}
            label={lang === 'ar' ? 'الوضع الليلي' : 'Mode sombre'}
            right={<ProfileSwitch on={theme === 'dark'} onChange={(v) => setTheme(v ? 'dark' : 'light')}/>} />
          <ProfileRow icon={<Icons.Globe size={18}/>} label={t.language}
            right={
              <div className="row" style={{ background: 'var(--surface-2)', padding: 3, borderRadius: 999 }}>
                {[{c:'fr',l:'FR'}, {c:'ar',l:'AR'}].map(o => (
                  <button key={o.c} onClick={() => setLang(o.c)}
                    style={{
                      padding: '6px 14px', borderRadius: 999,
                      background: lang === o.c ? 'var(--primary)' : 'transparent',
                      color: lang === o.c ? 'var(--primary-text)' : 'var(--text-2)',
                      fontWeight: 700, fontSize: 12,
                    }}>{o.l}</button>
                ))}
              </div>
            } />
          <ProfileRow icon={<Icons.Sparkle size={18}/>} label={lang === 'ar' ? 'الأسلوب' : 'Style'}
            right={
              <div className="row" style={{ background: 'var(--surface-2)', padding: 3, borderRadius: 999 }}>
                {[{c:'eco',l:'Eco'},{c:'premium',l:'Premium'}].map(o => (
                  <button key={o.c} onClick={() => setVariant(o.c)}
                    style={{
                      padding: '6px 12px', borderRadius: 999,
                      background: variant === o.c ? 'var(--primary)' : 'transparent',
                      color: variant === o.c ? 'var(--primary-text)' : 'var(--text-2)',
                      fontWeight: 700, fontSize: 11.5,
                    }}>{o.l}</button>
                ))}
              </div>
            } />
          <ProfileRow icon={<Icons.Bell size={18}/>} label={t.notifications}
            right={<ProfileSwitch on={true} />} />
        </ProfileSection>

        <ProfileSection>
          <ProfileRow icon={<Icons.Message size={18}/>} label={t.helpCenter} />
          <ProfileRow icon={<Icons.LogOut size={18}/>} label={t.logout} onClick={onLogout} danger />
        </ProfileSection>

        <div className="text-center t-tiny" style={{ paddingBlock: 8 }}>
          ewash · {t.appVersion} 1.0.0 (Casablanca)
        </div>
      </div>
    </div>
  );
}

function ProfileSection({ title, children }) {
  return (
    <div className="col gap-8">
      {title && <div className="t-tiny" style={{
        textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700,
        color: 'var(--text-3)', paddingInlineStart: 4,
      }}>{title}</div>}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {children}
      </div>
    </div>
  );
}

function ProfileRow({ icon, label, value, right, onClick, danger }) {
  return (
    <button onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '14px 16px', width: '100%',
      borderBottom: '1px solid var(--border)',
      textAlign: 'inherit', cursor: onClick ? 'pointer' : 'default',
      color: danger ? 'var(--danger)' : 'var(--text)',
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 10,
        background: danger ? 'rgba(229,72,77,0.12)' : 'var(--surface-2)',
        color: danger ? 'var(--danger)' : 'var(--text)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>{icon}</div>
      <div className="flex-1" style={{ fontWeight: 600, fontSize: 14.5 }}>{label}</div>
      {value && <div className="t-muted" style={{ fontSize: 13 }}>{value}</div>}
      {right || (onClick && !danger && <Icons.ChevronRight size={16} style={{ color: 'var(--text-3)' }}/>)}
    </button>
  );
}

function ProfileSwitch({ on, onChange }) {
  return (
    <button onClick={() => onChange && onChange(!on)} style={{
      width: 46, height: 28, borderRadius: 99,
      background: on ? 'var(--primary)' : 'var(--border-strong)',
      position: 'relative',
      transition: 'background 0.25s var(--ease-soft)',
      flexShrink: 0,
      boxShadow: on
        ? 'inset 0 1px 1px rgba(0,0,0,0.06), 0 4px 10px -4px color-mix(in srgb, var(--primary) 35%, transparent)'
        : 'inset 0 1px 2px rgba(0,0,0,0.05)',
    }}>
      <span style={{
        position: 'absolute', top: 3, insetInlineStart: on ? 21 : 3,
        width: 22, height: 22, borderRadius: 99,
        background: '#fff',
        transition: 'inset-inline-start 0.28s var(--ease-spring), box-shadow 0.2s',
        boxShadow: '0 1px 2px rgba(0,0,0,0.2), 0 3px 6px rgba(0,0,0,0.15)',
      }}/>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────
// SUPPORT (chat with team)
// ─────────────────────────────────────────────────────────────
function SupportScreen({ t, onBack, theme }) {
  const [messages, setMessages] = useS_h([
    { from: 'bot', text: t.supportTitle === 'Parler à l\'équipe'
      ? 'Bonjour ! Comment puis-je vous aider aujourd\'hui ?'
      : 'مرحباً! كيف يمكنني مساعدتك اليوم؟',
      time: '10:24' },
  ]);
  const [draft, setDraft] = useS_h('');
  const send = () => {
    if (!draft.trim()) return;
    const newMsgs = [...messages, { from: 'me', text: draft, time: '10:25' }];
    setMessages(newMsgs);
    setDraft('');
    setTimeout(() => {
      setMessages(prev => [...prev, {
        from: 'bot', time: '10:26',
        text: t.supportTitle === 'Parler à l\'équipe'
          ? 'Merci, votre message a bien été transmis à notre équipe. Un conseiller va vous répondre rapidement.'
          : 'شكراً، تم إرسال رسالتك إلى فريقنا. سيتواصل معك مستشار قريباً.',
      }]);
    }, 800);
  };
  return (
    <div className="col" style={{ flex: 1, background: 'var(--bg)' }}>
      <TopBar onBack={onBack}
        title={t.supportTitle}
        subtitle={<span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          color: 'var(--accent-soft-text)',
        }}>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--accent)' }}/>
          {t.supportSub}
        </span>}/>
      <div className="flex-1 app-scroll px-16 col gap-12" style={{ paddingTop: 8, paddingBottom: 12 }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: m.from === 'me' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth: '75%',
              background: m.from === 'me' ? 'var(--primary)' : 'var(--surface)',
              color: m.from === 'me' ? 'var(--primary-text)' : 'var(--text)',
              borderRadius: m.from === 'me' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
              padding: '10px 14px', fontSize: 14, lineHeight: 1.4,
              border: m.from === 'me' ? 'none' : '1px solid var(--border)',
            }}>
              {m.text}
              <div className="t-tiny" style={{
                marginTop: 4, textAlign: 'end',
                color: m.from === 'me' ? 'rgba(255,255,255,0.7)' : 'var(--text-3)',
              }}>{m.time}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{
        display: 'flex', gap: 8, padding: '10px 12px',
        borderTop: '1px solid var(--border)',
        background: 'var(--surface)',
      }}>
        <input className="input" placeholder={t.typeMessage}
          value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          style={{ flex: 1, background: 'var(--surface-2)', borderColor: 'transparent' }}/>
        <button onClick={send} style={{
          width: 48, height: 48, borderRadius: 99,
          background: 'var(--primary)', color: 'var(--primary-text)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <Icons.Send size={20}/>
        </button>
      </div>
    </div>
  );
}

Object.assign(window, { HomeScreen, BookingsScreen, ServicesScreen, ProfileScreen, SupportScreen });
