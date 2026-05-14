/* eslint-disable */
// ewash — main app

const { useState: useS_a, useEffect: useE_a, useMemo: useM_a } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "variant": "eco",
  "theme": "light",
  "lang": "fr"
}/*EDITMODE-END*/;

// ─────────────────────────────────────────────────────────────
// MAIN APP
// ─────────────────────────────────────────────────────────────
function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const { variant, theme, lang } = tweaks;

  const t = window.I18N[lang] || window.I18N.fr;
  const dir = lang === 'ar' ? 'rtl' : 'ltr';

  // App-level navigation state
  const [phase, setPhase] = useS_a('lang');
  // phase: splash → lang → app. Phone/OTP removed — phone is collected in the booking recap.
  const [tab, setTab] = useS_a('home'); // home, bookings, services, profile
  const [modal, setModal] = useS_a(null); // 'booking' | 'support' | null
  const [toast, setToast] = useS_a(null);

  const profile = useM_a(() => ({
    name: lang === 'ar' ? 'يوسف' : 'Youssef',
    phone: '6 11 20 45 02',
  }), [lang]);

  useE_a(() => {
    document.documentElement.setAttribute('data-variant', variant);
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('dir', dir);
  }, [variant, theme, dir]);

  // PWA: when installed (display-mode: standalone) or launched with ?pwa=1,
  // render the app full-viewport without the desktop phone-frame chrome.
  const isStandalone = useM_a(() => {
    if (typeof window === 'undefined') return false;
    try {
      if (window.matchMedia('(display-mode: standalone)').matches) return true;
    } catch (e) { /* ignore */ }
    if (window.navigator && window.navigator.standalone) return true;
    return new URLSearchParams(window.location.search).has('pwa');
  }, []);

  useE_a(() => {
    if (isStandalone) document.documentElement.setAttribute('data-pwa-standalone', '');
    else document.documentElement.removeAttribute('data-pwa-standalone');
  }, [isStandalone]);

  // ───── Phase rendering
  let phaseContent = null;
  if (phase === 'splash') {
    phaseContent = <SplashScreen t={t} onDone={() => setPhase('lang')} />;
  } else if (phase === 'lang') {
    phaseContent = <LangScreen t={t} lang={lang}
      setLang={(l) => setTweak('lang', l)}
      onDone={() => setPhase('app')}/>;
  } else if (phase === 'app') {
    phaseContent = (
      <>
        {!modal && tab === 'home' && (
          <HomeScreen t={t} lang={lang} variant={variant} theme={theme}
            profile={profile}
            openBooking={() => setModal('booking')}
            gotoSupport={() => setModal('support')}
            gotoTariffs={() => setTab('services')}/>
        )}
        {!modal && tab === 'bookings' && (
          <BookingsScreen t={t} lang={lang} openBooking={() => setModal('booking')} theme={theme}/>
        )}
        {!modal && tab === 'services' && (
          <ServicesScreen t={t} lang={lang} openBooking={() => setModal('booking')} theme={theme}/>
        )}
        {!modal && tab === 'profile' && (
          <ProfileScreen t={t} lang={lang}
            setLang={(l) => setTweak('lang', l)}
            theme={theme}
            setTheme={(th) => setTweak('theme', th)}
            variant={variant}
            setVariant={(v) => setTweak('variant', v)}
            profile={profile}
            onLogout={() => { setPhase('lang'); setTab('home'); }}/>
        )}
        {modal === 'booking' && (
          <BookingFlow t={t} lang={lang} theme={theme} variant={variant}
            profile={profile}
            onClose={() => setModal(null)}
            onComplete={() => { setModal(null); setTab('bookings'); setToast(t.bookingConfirmed); }}/>
        )}
        {modal === 'support' && (
          <SupportScreen t={t} theme={theme} onBack={() => setModal(null)}/>
        )}
        {!modal && (
          <BottomNav t={t} screen={tab} setScreen={setTab}/>
        )}
      </>
    );
  }

  return (
    <>
      {isStandalone ? (
        <div className="app-root" dir={dir} style={{ direction: dir, height: '100vh' }}>
          {phaseContent}
          <Toast message={toast} onDone={() => setToast(null)} />
        </div>
      ) : (
        <div className="stage" dir={dir}>
          <div className="stage-inner">
            <span className="stage-label">ewash · Android · {variant} · {lang.toUpperCase()}</span>
            <EwashFrame theme={theme}>
              <div className="app-root" dir={dir} style={{ direction: dir }}>
                {phaseContent}
                <Toast message={toast} onDone={() => setToast(null)} />
              </div>
            </EwashFrame>
          </div>
        </div>
      )}

      <TweaksPanel>
        <TweakSection label="Direction" />
        <TweakRadio label="Style" value={variant}
          onChange={(v) => setTweak('variant', v)}
          options={[
            { label: 'Eco', value: 'eco' },
            { label: 'Premium', value: 'premium' },
          ]}/>
        <TweakRadio label="Mode" value={theme}
          onChange={(v) => setTweak('theme', v)}
          options={[
            { label: 'Light', value: 'light' },
            { label: 'Dark', value: 'dark' },
          ]}/>
        <TweakSection label="Localization" />
        <TweakRadio label="Language" value={lang}
          onChange={(v) => setTweak('lang', v)}
          options={[
            { label: 'FR', value: 'fr' },
            { label: 'AR', value: 'ar' },
          ]}/>
        <TweakSection label="Flow" />
        <TweakButton label="Replay onboarding"
          onClick={() => { setPhase('splash'); setTab('home'); setModal(null); }}/>
        <TweakButton label="Skip to app"
          onClick={() => { setPhase('app'); setModal(null); }}/>
        <TweakButton label="Start a booking"
          onClick={() => { setPhase('app'); setModal('booking'); }}/>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
