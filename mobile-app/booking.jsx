/* eslint-disable */
// ewash — booking flow (full WhatsApp-bot logic, made nice)

const { useState: useS_b, useEffect: useE_b, useMemo: useM_b } = React;

// Step ordering depends on vehicle kind
const STEPS_CAR = ['category', 'vehicle', 'location', 'service', 'date', 'note'];
const STEPS_MOTO = ['category', 'location', 'service', 'date', 'note'];
const MOTO_CATEGORY = 'MOTO';
const DEFAULT_STAFF_CONTACT = { available: false, whatsapp_phone: '' };

const CATEGORY_ICONS = {
  A: Icons.Car,
  B: Icons.CarSide,
  C: Icons.Suv,
  MOTO: Icons.Moto,
};

const SERVICE_DURATIONS = {
  svc_ext: 25,
  svc_cpl: 45,
  svc_sal: 150,
  svc_pol: 180,
  svc_cer6m: 120,
  svc_cer6w: 60,
  svc_cuir: 70,
  svc_plastq: 55,
  svc_optq: 45,
  svc_lustre: 90,
  svc_scooter: 25,
  svc_moto: 35,
};

function _isMotoCategory(category) {
  return category === MOTO_CATEGORY;
}

function _categoryIcon(categoryId) {
  return CATEGORY_ICONS[categoryId] || Icons.Car;
}

function _categoryLabel(t, category, categoryId) {
  if (!categoryId) return '';
  if (_isMotoCategory(categoryId)) return t.catMoto || (category && category.label) || 'Moto';
  return t['cat' + categoryId] || (category && category.label) || categoryId;
}

function _categorySub(t, category) {
  if (!category) return '';
  if (_isMotoCategory(category.id)) return t.catMotoSub || category.sub || '';
  return t['cat' + category.id + 'Sub'] || category.sub || '';
}

function _normalizeService(service) {
  if (!service) return null;
  return Object.assign({}, service, {
    durationMin: service.durationMin || SERVICE_DURATIONS[service.id] || 45,
  });
}

function _servicesForCategory(bootstrap, category) {
  if (!bootstrap || !bootstrap.services || !category) return [];
  if (_isMotoCategory(category)) return (bootstrap.services.moto || []).map(_normalizeService);
  return []
    .concat(bootstrap.services.wash || [])
    .concat(bootstrap.services.detailing || [])
    .map(_normalizeService);
}

function _addonOptions(bootstrap) {
  if (!bootstrap || !bootstrap.services) return [];
  return (bootstrap.services.detailing || []).map(_normalizeService);
}

function _findById(items, id) {
  return (items || []).find((item) => item.id === id) || null;
}

function _centerLabel(centers, centerId) {
  const center = _findById(centers, centerId);
  return center ? center.name : '';
}

function _slotStartMinutes(slot) {
  const match = slot && slot.id ? /^slot_(\d+)_\d+$/.exec(slot.id) : null;
  if (!match) return 0;
  return Number(match[1]) * 60;
}

function _slotLabel(slots, slotId) {
  const slot = _findById(slots, slotId);
  return slot ? slot.label : '';
}

function _addonPreviewPrice(addon) {
  if (!addon) return 0;
  return Math.round((addon.price_dh || 0) * 0.9);
}

function _bookingDataSize(data) {
  try {
    return JSON.stringify(data).length;
  } catch (_) {
    return 0;
  }
}

function _payloadFromBookingData(d) {
  const serviceId = d.service && d.service.id ? d.service.id : d.service;
  return {
    phone: d.phone,
    name: d.name,
    category: d.category,
    vehicle: d.category !== MOTO_CATEGORY ? {
      make: d.make,
      color: d.color,
      plate: d.plate || null,
    } : null,
    location: {
      kind: d.locationKind,
      pin_address: d.locationKind === 'home' ? d.pinAddress : null,
      address_details: d.addressDetails || null,
      center_id: d.locationKind === 'center' ? d.centerId : null,
    },
    promo_code: d.promoApplied ? d.promoCode : null,
    service_id: serviceId,
    date: d.date && d.date.iso,
    slot: d.time,
    note: d.note || null,
    addon_ids: d.addons || [],
    client_request_id: d.clientRequestId,
  };
}

function _submitErrorMessage(t, err) {
  if (err && err.status === 429) return t.submitRateLimited || t.networkErrorTitle;
  return t.submitBookingError || t.networkErrorTitle;
}

// ─────────────────────────────────────────────────────────────
// BOOKING ROOT — state machine
// ─────────────────────────────────────────────────────────────
function BookingFlow({ t, lang, theme, variant, onClose, onComplete, profile }) {
  const [data, setData] = useS_b({
    name: profile.name,
    phone: '', // collected in the recap step (replaces the old OTP login flow)
    category: null, // 'A' | 'B' | 'C' | 'MOTO'
    make: '', color: '', plate: '',
    locationKind: null, // 'home' | 'center'
    pinAddress: '173 Bd Anfa, Casablanca',
    addressDetails: '',
    centerId: null,
    promoCode: null,
    promoApplied: false,
    service: null,
    date: null, // { d, m, y, label }
    time: null,
    note: '',
    addons: [],
  });

  const [step, setStep] = useS_b('category');
  const [history, setHistory] = useS_b([]);
  const [toastMsg, setToastMsg] = useS_b(null);
  const [bootstrap, setBootstrap] = useS_b(null);
  const [bootstrapErr, setBootstrapErr] = useS_b(null);
  const [bootstrapLoading, setBootstrapLoading] = useS_b(false);
  const [bootstrapRetry, setBootstrapRetry] = useS_b(0);
  const [confirmedRef, setConfirmedRef] = useS_b('');
  const [confirmedTotal, setConfirmedTotal] = useS_b(null);

  const kind = _isMotoCategory(data.category) ? 'moto' : 'car';
  const stepperSteps = kind === 'moto' ? STEPS_MOTO : STEPS_CAR;
  const categoriesList = bootstrap?.categories || [];
  const centersList = bootstrap?.centers || [];
  const servicesList = useM_b(
    () => _servicesForCategory(bootstrap, data.category),
    [bootstrap, data.category]
  );
  const addonsList = useM_b(() => _addonOptions(bootstrap), [bootstrap]);
  const closedDatesSet = useM_b(
    () => new Set((bootstrap && bootstrap.closed_dates) || []),
    [bootstrap]
  );
  const slotsList = bootstrap?.time_slots || [];
  const staffContact = bootstrap?.staff_contact || DEFAULT_STAFF_CONTACT;

  useE_b(() => {
    let alive = true;
    setBootstrapLoading(true);
    setBootstrapErr(null);
    window.EwashAPI.getBootstrap({})
      .then((payload) => {
        if (!alive) return;
        setBootstrap(payload);
        setBootstrapLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setBootstrapErr(err);
        setBootstrapLoading(false);
        if (window.EwashLog) {
          window.EwashLog.warn('booking.error', {
            step: 'bootstrap',
            error_code: (err && err.error_code) || 'bootstrap_failed',
          });
        }
      });
    return () => { alive = false; };
  }, [bootstrapRetry]);

  useE_b(() => {
    if (!data.category) return undefined;
    let alive = true;
    setBootstrapLoading(true);
    window.EwashAPI.getBootstrap({
      category: data.category,
      promo: data.promoApplied ? data.promoCode : null,
    })
      .then((payload) => {
        if (!alive) return;
        setBootstrap(payload);
        setBootstrapLoading(false);
      })
      .catch((err) => {
        if (!alive) return;
        setBootstrapErr(err);
        setBootstrapLoading(false);
        if (window.EwashLog) {
          window.EwashLog.warn('booking.error', {
            step: 'bootstrap_category',
            error_code: (err && err.error_code) || 'bootstrap_failed',
          });
        }
      });
    return () => { alive = false; };
  }, [data.category, data.promoApplied, data.promoCode, bootstrapRetry]);

  useE_b(() => {
    if (!data.service || !servicesList.length) return;
    const refreshed = _findById(servicesList, data.service.id);
    if (refreshed && refreshed.price_dh !== data.service.price_dh) {
      patch({ service: refreshed });
    }
  }, [servicesList, data.service]);

  // For step indicator
  const stepperKey = step === 'addressPin' ? 'location'
    : step === 'centers' ? 'location'
    : step === 'promo' ? 'service'
    : step === 'time' ? 'date'
    : step;
  const stepperIdx = stepperSteps.indexOf(stepperKey);

  const goTo = (next) => {
    if (window.EwashLog) {
      window.EwashLog.info('booking.flow', {
        from_step: step,
        to_step: next,
        data_size: _bookingDataSize(data),
      });
    }
    setHistory((h) => [...h, step]);
    setStep(next);
  };
  const back = () => {
    setHistory((h) => {
      if (h.length === 0) { onClose(); return h; }
      const prev = h[h.length - 1];
      if (window.EwashLog) {
        window.EwashLog.info('booking.flow', {
          from_step: step,
          to_step: prev,
          data_size: _bookingDataSize(data),
        });
      }
      setStep(prev);
      return h.slice(0, -1);
    });
  };
  const patch = (p) => setData((d) => ({ ...d, ...p }));

  const totalPrice = useM_b(() => {
    if (!data.service || !data.category) return 0;
    const base = data.service.price_dh || 0;
    const addonsTotal = data.addons.reduce((s, id) => {
      const addon = _findById(addonsList, id);
      return s + _addonPreviewPrice(addon);
    }, 0);
    return base + addonsTotal;
  }, [data, addonsList]);

  const retryBootstrap = () => {
    setBootstrapErr(null);
    setBootstrapRetry((n) => n + 1);
  };

  const submitBooking = async () => {
    const payload = _payloadFromBookingData(data);
    const response = await window.EwashAPI.submitBooking(payload);
    setConfirmedRef(response.ref);
    setConfirmedTotal(response.total_dh);
    setStep('confirmed');
  };

  // ───── render
  return (
    <div className="col" style={{ flex: 1, background: 'var(--bg)' }}>
      <BookingHeader
        t={t} step={step} onBack={back} onClose={onClose}
        stepperIdx={stepperIdx} stepperTotal={stepperSteps.length}
        showStepper={!['confirmed', 'addons', 'recap'].includes(step)}
      />

      <div className="app-scroll flex-1">
        {bootstrapErr && !bootstrap && (
          <BookingBootstrapError t={t} onRetry={retryBootstrap} />
        )}
        {!bootstrapErr && !bootstrap && (
          <BookingFlowSkeleton t={t} />
        )}
        {bootstrap && (
          <>
        {step === 'category' && (
          <CategoryStep t={t} data={data} patch={patch} categories={categoriesList} onNext={() => {
            // moto skips vehicle details + promo step
            if (_isMotoCategory(data.category)) goTo('location');
            else goTo('vehicle');
          }}/>
        )}
        {step === 'vehicle' && (
          <VehicleStep t={t} data={data} patch={patch} onNext={() => goTo('location')}/>
        )}
        {step === 'location' && (
          <LocationStep t={t} data={data} centers={centersList}
            onHome={() => { patch({ locationKind: 'home' }); goTo('addressPin'); }}
            onCenter={() => { patch({ locationKind: 'center' }); goTo('centers'); }}/>
        )}
        {step === 'addressPin' && (
          <AddressPinStep t={t} data={data} patch={patch}
            onNext={() => goTo(_isMotoCategory(data.category) ? 'service' : 'promo')}/>
        )}
        {step === 'centers' && (
          <CentersStep t={t} data={data} centers={centersList}
            onNext={(id) => { patch({ centerId: id }); goTo(_isMotoCategory(data.category) ? 'service' : 'promo'); }}/>
        )}
        {step === 'promo' && (
          <PromoStep t={t} data={data} patch={patch}
            onNext={() => goTo('service')}
            showToast={setToastMsg}/>
        )}
        {step === 'service' && (
          <ServiceStep t={t} data={data} patch={patch}
            services={servicesList}
            loading={bootstrapLoading}
            onNext={() => goTo('date')}/>
        )}
        {step === 'date' && (
          <DateStep t={t} lang={lang} data={data} patch={patch}
            closedDatesSet={closedDatesSet}
            onNext={() => goTo('time')}/>
        )}
        {step === 'time' && (
          <TimeStep t={t} data={data} patch={patch} slots={slotsList}
            onNext={() => goTo('note')}/>
        )}
        {step === 'note' && (
          <NoteStep t={t} data={data} patch={patch}
            onNext={() => setStep('recap')}/>
        )}
        {step === 'recap' && (
          <RecapStep t={t} lang={lang} data={data} patch={patch}
            categories={categoriesList}
            centers={centersList}
            slots={slotsList}
            staffContact={staffContact}
            totalPrice={totalPrice}
            onEdit={() => setStep('category')}
            onCancel={onClose}
            onConfirm={submitBooking}
            showToast={setToastMsg}/>
        )}
        {step === 'confirmed' && (
          <ConfirmedStep t={t} lang={lang} data={data} totalPrice={totalPrice}
            confirmedRef={confirmedRef}
            confirmedTotal={confirmedTotal}
            variant={variant}
            centers={centersList}
            slots={slotsList}
            addons={addonsList}
            staffContact={staffContact}
            onAddons={() => setStep('addons')}
            onDone={onComplete}/>
        )}
        {step === 'addons' && (
          <AddonsStep t={t} data={data} patch={patch} addons={addonsList}
            totalPrice={totalPrice} onDone={onComplete}/>
        )}
          </>
        )}
      </div>

      {/* footer CTAs are rendered inside each step */}
      <Toast message={toastMsg} onDone={() => setToastMsg(null)} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Header with stepper
// ─────────────────────────────────────────────────────────────
function BookingHeader({ t, step, onBack, onClose, stepperIdx, stepperTotal, showStepper }) {
  const titleMap = {
    category: t.chooseCategory,
    vehicle: t.vehicleDetails,
    location: t.whereService,
    addressPin: t.pinAddress,
    centers: t.pickCenter,
    promo: t.promo,
    service: t.chooseService,
    date: t.chooseDate,
    time: t.chooseTime,
    note: t.addNote,
    recap: t.recap,
    confirmed: t.bookingConfirmed,
    addons: t.addonsTitle,
  };
  return (
    <div style={{ background: 'var(--bg)' }}>
      <div className="appbar">
        <button className="icon-btn" onClick={onBack}><Icons.ChevronLeft size={22}/></button>
        <div className="t-tiny" style={{ fontWeight: 700, letterSpacing: '0.05em' }}>
          {showStepper && stepperIdx >= 0 && (
            <>{t.step} {stepperIdx + 1} {t.stepOf} {stepperTotal}</>
          )}
        </div>
        <button className="icon-btn" onClick={onClose}><Icons.Close size={20}/></button>
      </div>
      {showStepper && stepperIdx >= 0 && (
        <Stepper current={stepperIdx} total={stepperTotal} />
      )}
    </div>
  );
}

function BookingFlowSkeleton({ t, title, subtitle }) {
  return (
    <div className="px-16 col gap-12" style={{ paddingTop: 18, paddingBottom: 100 }}>
      <div className="px-4 col gap-6 mb-4">
        <div className="t-h1">{title || t.chooseCategory}</div>
        <div className="t-muted">{subtitle || t.loadingCatalog}</div>
      </div>
      {[0, 1, 2].map((idx) => (
        <div key={idx} className="booking-skeleton-card">
          <div className="booking-skeleton-icon" />
          <div className="col gap-8 flex-1">
            <div className="booking-skeleton-line" style={{ width: idx === 1 ? '52%' : '64%' }} />
            <div className="booking-skeleton-line small" style={{ width: idx === 2 ? '72%' : '86%' }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function BookingBootstrapError({ t, onRetry }) {
  return (
    <div className="px-16 col gap-12" style={{ paddingTop: 24, paddingBottom: 100 }}>
      <div className="card" style={{ padding: 18 }}>
        <div className="row gap-12" style={{ alignItems: 'flex-start' }}>
          <div style={{
            width: 44, height: 44, borderRadius: 14,
            background: 'color-mix(in srgb, var(--danger) 14%, transparent)',
            color: 'var(--danger)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <Icons.Close size={22}/>
          </div>
          <div className="col gap-6 flex-1">
            <div style={{ fontWeight: 800, fontSize: 16 }}>{t.networkErrorTitle}</div>
            <div className="t-muted">{t.networkErrorBody}</div>
          </div>
        </div>
        <Btn block style={{ marginTop: 16 }} onClick={onRetry}>{t.retry}</Btn>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Category
// ─────────────────────────────────────────────────────────────
function CategoryStep({ t, data, patch, categories, onNext }) {
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.chooseCategory}</div>
        <div className="t-muted">{t.chooseCategorySub}</div>
      </div>
      <div className="px-16 col gap-10 anim-stagger" style={{ paddingBottom: 100 }}>
        {categories.map(c => {
          const Icon = _categoryIcon(c.id);
          return (
          <SelectCard key={c.id}
            selected={data.category === c.id}
            onClick={() => patch({
              category: c.id,
              service: null,
              addons: [],
              promoCode: null,
              promoApplied: false,
            })}
            icon={<Icon size={28}/>}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{_categoryLabel(t, c, c.id)}</div>
            <div className="t-muted" style={{ fontSize: 12.5 }}>{_categorySub(t, c)}</div>
          </SelectCard>
          );
        })}
      </div>
      <CtaDock>
        <Btn block lg disabled={!data.category}
          onClick={onNext}
          style={{ opacity: data.category ? 1 : 0.4 }}>
          {t.next}
        </Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Vehicle details
// ─────────────────────────────────────────────────────────────
function VehicleStep({ t, data, patch, onNext }) {
  const colors = ['Noir', 'Blanc', 'Gris', 'Argent', 'Bleu', 'Rouge'];
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.vehicleDetails}</div>
        <div className="t-muted">{t.vehicleDetailsSub}</div>
      </div>
      <div className="px-20 col gap-16" style={{ paddingBottom: 100 }}>
        <Field label={t.makeModel}>
          <input className="input" placeholder={t.makeModelPh}
            value={data.make} onChange={(e) => patch({ make: e.target.value })}/>
        </Field>
        <Field label={t.color}>
          <div className="col gap-10">
            <input className="input" placeholder={t.colorPh}
              value={data.color} onChange={(e) => patch({ color: e.target.value })}/>
            <div className="row wrap gap-8">
              {colors.map(c => {
                const sel = data.color.trim().toLowerCase() === c.toLowerCase();
                return (
                  <button key={c} type="button" onClick={() => patch({ color: c })}
                    className="chip"
                    style={{
                      cursor: 'pointer',
                      borderColor: sel ? 'var(--primary)' : 'var(--border)',
                      background: sel ? 'var(--primary-soft)' : 'var(--chip-bg)',
                      color: sel ? 'var(--primary-soft-text)' : 'var(--text-2)',
                      padding: '8px 14px',
                      fontSize: 13,
                      fontWeight: sel ? 700 : 600,
                      boxShadow: sel
                        ? '0 4px 10px -4px color-mix(in srgb, var(--primary) 35%, transparent)'
                        : 'none',
                    }}>{c}</button>
                );
              })}
            </div>
          </div>
        </Field>
        <Field label={t.plateOptional}>
          <input className="input" placeholder="123456 - أ - 7"
            value={data.plate} onChange={(e) => patch({ plate: e.target.value })}/>
        </Field>
      </div>
      <CtaDock>
        <Btn block lg disabled={!data.make || !data.color} onClick={onNext}
          style={{ opacity: (data.make && data.color) ? 1 : 0.4 }}>{t.next}</Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Location
// ─────────────────────────────────────────────────────────────
function LocationStep({ t, centers, onHome, onCenter }) {
  const firstCenter = centers[0];
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.whereService}</div>
        <div className="t-muted">{t.locationSub}</div>
      </div>
      <div className="px-16 col gap-12" style={{ paddingBottom: 100 }}>
        <button onClick={onHome} className="card" style={{
          padding: 18, display: 'flex', gap: 14, alignItems: 'flex-start',
          textAlign: 'inherit',
        }}>
          <div style={{
            width: 60, height: 60, borderRadius: 16,
            background: 'var(--primary-soft)', color: 'var(--primary-soft-text)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}><Icons.Pin size={28}/></div>
          <div className="col gap-4 flex-1">
            <div style={{ fontWeight: 700, fontSize: 16 }}>{t.atHome}</div>
            <div className="t-muted">{t.atHomeSub}</div>
            <div className="row gap-6 mt-4">
              <span className="chip chip-accent" style={{ fontSize: 10.5, padding: '3px 8px' }}>
                <Icons.Leaf size={10}/> Recommandé
              </span>
            </div>
          </div>
          <Icons.ChevronRight size={20} style={{ color: 'var(--text-3)', alignSelf: 'center' }}/>
        </button>

        <button onClick={onCenter} className="card" style={{
          padding: 18, display: 'flex', gap: 14, alignItems: 'flex-start',
          textAlign: 'inherit',
        }}>
          <div style={{
            width: 60, height: 60, borderRadius: 16,
            background: 'var(--surface-2)', color: 'var(--text)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}><Icons.Home size={28}/></div>
          <div className="col gap-4 flex-1">
            <div style={{ fontWeight: 700, fontSize: 16 }}>{t.atCenter}</div>
            <div className="t-muted">{t.atCenterSub}</div>
            <div className="t-tiny mt-4" style={{ color: 'var(--text-2)' }}>
              {firstCenter ? firstCenter.name : t.atCenterSub}
            </div>
          </div>
          <Icons.ChevronRight size={20} style={{ color: 'var(--text-3)', alignSelf: 'center' }}/>
        </button>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Address pin
// ─────────────────────────────────────────────────────────────
function AddressPinStep({ t, data, patch, onNext }) {
  return (
    <>
      <div className="px-20 col gap-6 mb-12">
        <div className="t-h1">{t.pinAddress}</div>
        <div className="t-muted">{t.pinAddressSub}</div>
      </div>
      <div style={{ padding: '0 16px' }}>
        <div className="map-bg" style={{
          height: 220, borderRadius: 20,
          position: 'relative', overflow: 'hidden',
          border: '1px solid var(--border)',
        }}>
          {/* roads */}
          <svg viewBox="0 0 360 220" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
            <path d="M-20 130 Q90 100, 180 140 T380 110" stroke="var(--border-strong)" strokeWidth="14" fill="none" opacity="0.7"/>
            <path d="M-20 130 Q90 100, 180 140 T380 110" stroke="var(--surface)" strokeWidth="10" fill="none" />
            <path d="M60 -20 L120 240" stroke="var(--border-strong)" strokeWidth="10" fill="none" opacity="0.7"/>
            <path d="M60 -20 L120 240" stroke="var(--surface)" strokeWidth="6" fill="none"/>
            <path d="M250 0 L240 240" stroke="var(--border-strong)" strokeWidth="10" fill="none" opacity="0.5"/>
            <path d="M250 0 L240 240" stroke="var(--surface)" strokeWidth="6" fill="none"/>
          </svg>
          {/* pin centered */}
          <div style={{
            position: 'absolute', left: '50%', top: '50%',
            transform: 'translate(-50%, -100%)',
            color: 'var(--primary)',
          }}>
            <svg width="40" height="48" viewBox="0 0 40 48" fill="none">
              <path d="M20 4 C30 4 36 12 36 20 C36 32 20 44 20 44 S4 32 4 20 C4 12 10 4 20 4z"
                fill="var(--primary)" stroke="var(--surface)" strokeWidth="3"/>
              <circle cx="20" cy="20" r="6" fill="var(--surface)"/>
            </svg>
          </div>
          {/* ripple */}
          <div style={{
            position: 'absolute', left: '50%', top: '50%',
            transform: 'translate(-50%, -50%)',
            width: 32, height: 32, borderRadius: 99,
            background: 'var(--primary)', opacity: 0.2,
            animation: 'ripple 2s infinite',
          }}/>
          {/* recenter button */}
          <button style={{
            position: 'absolute', insetInlineEnd: 12, bottom: 12,
            width: 40, height: 40, borderRadius: 12,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: 'var(--shadow-sm)',
          }}>
            <Icons.Navigation size={18} style={{ color: 'var(--primary)' }}/>
          </button>
        </div>
      </div>
      <div className="px-20 col gap-16 mt-16" style={{ paddingBottom: 100 }}>
        <div className="card-soft" style={{ padding: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
          <Icons.Pin size={20} style={{ color: 'var(--primary)' }}/>
          <div className="col flex-1">
            <div style={{ fontWeight: 700, fontSize: 14 }}>{data.pinAddress}</div>
            <div className="t-tiny">{t.yourLocation}</div>
          </div>
          <button className="icon-btn"><Icons.Edit size={16}/></button>
        </div>
        <Field label={t.addressDetails}>
          <textarea className="input" rows={3}
            placeholder={t.addressDetailsPh}
            value={data.addressDetails}
            onChange={(e) => patch({ addressDetails: e.target.value })}
            style={{ resize: 'none' }}/>
        </Field>
      </div>
      <CtaDock>
        <Btn block lg onClick={onNext}>{t.next}</Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Centers
// ─────────────────────────────────────────────────────────────
function CentersStep({ t, centers, onNext }) {
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.pickCenter}</div>
        <div className="t-muted">{centers[0] ? centers[0].name : t.atCenterSub}</div>
      </div>
      <div className="px-16 col gap-10 anim-stagger" style={{ paddingBottom: 24 }}>
        {centers.map(c => (
          <button key={c.id} onClick={() => onNext(c.id)} className="card" style={{
            padding: 14, display: 'flex', gap: 12, alignItems: 'flex-start',
            textAlign: 'inherit',
          }}>
            <div style={{
              width: 48, height: 48, borderRadius: 14,
              background: 'var(--primary-soft)', color: 'var(--primary-soft-text)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}><Icons.Pin size={22}/></div>
            <div className="col gap-4 flex-1" style={{ minWidth: 0 }}>
              <div className="row between">
                <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
              </div>
              <div className="t-muted">{c.details}</div>
              <div className="row gap-6 mt-4">
                <span className="chip chip-accent" style={{ fontSize: 10.5, padding: '3px 8px' }}>
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: 'currentColor' }}/>
                  {t.open}
                </span>
              </div>
            </div>
            <Icons.ChevronRight size={18} style={{ color: 'var(--text-3)', marginTop: 14 }}/>
          </button>
        ))}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Promo code
// ─────────────────────────────────────────────────────────────
function PromoStep({ t, data, patch, onNext, showToast }) {
  const [open, setOpen] = useS_b(false);
  const [code, setCode] = useS_b('');
  const [err, setErr] = useS_b(false);
  const [loading, setLoading] = useS_b(false);
  const apply = () => {
    const normalized = code.trim().toUpperCase();
    if (!normalized || loading) return;
    setLoading(true);
    setErr(false);
    window.EwashAPI.validatePromo({ code: normalized, category: data.category })
      .then((result) => {
        if (result && result.valid) {
          patch({ promoCode: normalized, promoApplied: true });
          showToast(result.label || t.promoValid);
          setTimeout(onNext, 600);
        } else {
          patch({ promoCode: null, promoApplied: false });
          setErr(true);
        }
      })
      .catch((error) => {
        patch({ promoCode: null, promoApplied: false });
        setErr(true);
        if (window.EwashLog) {
          window.EwashLog.warn('booking.error', {
            step: 'promo',
            error_code: (error && error.error_code) || 'promo_validate_failed',
          });
        }
      })
      .finally(() => setLoading(false));
  };
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.promoQuestion}</div>
        <div className="t-muted">{t.promoSub}</div>
      </div>
      <div className="px-16 col gap-12" style={{ paddingBottom: 100 }}>
        {!open ? (
          <>
            <button onClick={() => setOpen(true)} className="card" style={{
              padding: 16, display: 'flex', gap: 12, alignItems: 'center', textAlign: 'inherit',
            }}>
              <div style={{
                width: 48, height: 48, borderRadius: 14,
                background: 'var(--accent-soft)', color: 'var(--accent-soft-text)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}><Icons.Tag size={22}/></div>
              <div className="col flex-1 gap-2">
                <div style={{ fontWeight: 700, fontSize: 15 }}>{t.enterPromo}</div>
                <div className="t-muted">{t.promoSub}</div>
              </div>
              <Icons.ChevronRight size={18} style={{ color: 'var(--text-3)' }}/>
            </button>
            <button onClick={() => { patch({ promoCode: null, promoApplied: false }); onNext(); }} className="card-soft" style={{
              padding: 14, fontWeight: 600, fontSize: 14,
              color: 'var(--text-2)', borderRadius: 16,
            }}>{t.noPromo}</button>
          </>
        ) : (
          <>
            <div className="card" style={{ padding: 16 }}>
              <Field label={t.enterPromo}>
                <input className="input" autoFocus
                  placeholder="ECO15"
                  value={code}
                  onChange={(e) => { setCode(e.target.value.toUpperCase()); setErr(false); }}
                  style={{
                    fontSize: 18, fontWeight: 700, letterSpacing: '0.15em',
                    fontFamily: 'var(--font-display)',
                    borderColor: err ? 'var(--danger)' : 'var(--border)',
                  }}/>
              </Field>
              {err && (
                <div className="row gap-6 mt-8" style={{ color: 'var(--danger)' }}>
                  <Icons.Close size={14}/>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{t.promoInvalid}</span>
                </div>
              )}
              <div className="row gap-8 mt-12">
                <Btn variant="soft" style={{ flex: 1 }} onClick={() => setOpen(false)}>
                  {t.cancel}
                </Btn>
                <Btn style={{ flex: 1 }} onClick={apply} disabled={!code || loading}>
                  {loading ? t.loadingCatalog : t.applyPromo}
                </Btn>
              </div>
            </div>
            <button onClick={() => { patch({ promoCode: null, promoApplied: false }); onNext(); }} className="t-muted" style={{
              padding: 14, textAlign: 'center', fontWeight: 600,
            }}>{t.noPromo}</button>
          </>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Service
// ─────────────────────────────────────────────────────────────
function ServiceStep({ t, data, patch, onNext, services, loading }) {
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.chooseService}</div>
        <div className="t-muted">{t.serviceSub}</div>
      </div>
      <div className="px-16 col gap-10 anim-stagger" style={{ paddingBottom: 100 }}>
        {loading && !services.length && (
          <BookingFlowSkeleton t={t} title={t.chooseService} subtitle={t.loadingCatalog} />
        )}
        {services.map((s, i) => {
          const selected = data.service?.id === s.id;
          const price = s.price_dh || 0;
          const regularPrice = s.regular_price_dh;
          return (
            <button key={i} onClick={() => patch({ service: s })}
              className={`svc-card ${selected ? 'selected' : ''}`}
              style={{ textAlign: 'inherit', width: '100%', padding: 14 }}>
              <div className="col gap-6 flex-1" style={{ minWidth: 0 }}>
                <div className="row between">
                  <div style={{ fontWeight: 700, fontSize: 14.5 }}>{s.name}</div>
                  {s.popular && (
                    <span className="chip chip-primary" style={{
                      fontSize: 10, padding: '2px 8px',
                    }}>★ {t.mostPopular}</span>
                  )}
                </div>
                <div className="t-muted" style={{ fontSize: 12.5 }}>{s.desc}</div>
                <div className="row gap-12 mt-4" style={{ alignItems: 'baseline' }}>
                  <div className="row gap-2" style={{ alignItems: 'baseline' }}>
                    {regularPrice ? (
                      <>
                        <span className="t-num" style={{ fontWeight: 800, fontSize: 17, color: 'var(--accent-soft-text)' }}>
                          {price}
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text-3)', textDecoration: 'line-through' }}>{regularPrice}</span>
                      </>
                    ) : (
                      <span className="t-num" style={{ fontWeight: 800, fontSize: 17 }}>{price}</span>
                    )}
                    <span className="t-tiny" style={{ color: 'var(--text-2)' }}>DH</span>
                  </div>
                  <span className="t-tiny" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <Icons.Clock size={11}/> {s.durationMin} {t.min}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <CtaDock>
        <Btn block lg disabled={!data.service} onClick={onNext}
          style={{ opacity: data.service ? 1 : 0.4 }}>{t.next}</Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Date
// ─────────────────────────────────────────────────────────────
function DateStep({ t, lang, data, patch, onNext, closedDatesSet }) {
  const [showMore, setShowMore] = useS_b(false);
  const start = useM_b(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }, []);
  const days = Array.from({ length: showMore ? 14 : 7 }).map((_, i) => {
    const dt = new Date(start);
    dt.setDate(dt.getDate() + i);
    return {
      d: dt.getDate(),
      m: dt.getMonth(),
      y: dt.getFullYear(),
      iso: [
        dt.getFullYear(),
        String(dt.getMonth() + 1).padStart(2, '0'),
        String(dt.getDate()).padStart(2, '0'),
      ].join('-'),
      dow: t.days[dt.getDay()],
      isToday: i === 0,
      isTomorrow: i === 1,
    };
  });
  const isSel = (d) => data.date && data.date.d === d.d && data.date.m === d.m;
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.chooseDate}</div>
        <div className="t-muted">{t.chooseDateSub}</div>
      </div>
      <div className="px-16 col gap-12" style={{ paddingBottom: 100 }}>
        <div className="row wrap gap-8">
          {days.map((d, i) => {
            const sel = isSel(d);
            const closed = closedDatesSet.has(d.iso);
            return (
              <button key={i} onClick={() => { if (!closed) patch({ date: d, time: null }); }} className="press"
                disabled={closed}
                style={{
                  width: 'calc(25% - 6px)',
                  padding: '12px 0', borderRadius: 14,
                  background: closed ? 'var(--surface-2)' : sel ? 'var(--primary)' : 'var(--surface)',
                  color: closed ? 'var(--text-3)' : sel ? 'var(--primary-text)' : 'var(--text)',
                  border: `1px solid ${sel ? 'var(--primary)' : 'var(--border)'}`,
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
                  cursor: closed ? 'not-allowed' : 'pointer',
                  opacity: closed ? 0.52 : 1,
                  boxShadow: sel
                    ? '0 8px 18px -8px color-mix(in srgb, var(--primary) 60%, transparent)'
                    : 'none',
                  transform: sel ? 'translateY(-1px)' : 'translateY(0)',
                  transition: 'background 0.18s var(--ease-soft), border-color 0.18s var(--ease-soft), color 0.18s var(--ease-soft), box-shadow 0.22s var(--ease-soft), transform 0.22s var(--ease-spring)',
                }}>
                <span className="t-tiny" style={{
                  fontWeight: 700, letterSpacing: '0.06em',
                  color: sel ? 'rgba(255,255,255,0.86)' : 'var(--text-3)',
                }}>{d.dow.toUpperCase()}</span>
                <span className="t-num" style={{ fontWeight: 800, fontSize: 20 }}>{d.d}</span>
                <span className="t-tiny" style={{
                  color: sel ? 'rgba(255,255,255,0.78)' : 'var(--text-2)',
                }}>{t.months[d.m]}</span>
              </button>
            );
          })}
        </div>
        <button onClick={() => setShowMore(!showMore)}
          className="t-muted"
          style={{
            padding: 12, fontWeight: 600,
            color: 'var(--primary)', textAlign: 'center',
          }}>
          {showMore ? t.showLessDates : t.showMoreDates}
        </button>
      </div>
      <CtaDock>
        <Btn block lg disabled={!data.date} onClick={onNext}
          style={{ opacity: data.date ? 1 : 0.4 }}>{t.next}</Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Time
// ─────────────────────────────────────────────────────────────
function TimeStep({ t, data, patch, onNext, slots }) {
  // If the chosen date is today, only show slots ≥ now + 2h.
  const groupedSlots = useM_b(() => {
    const now = new Date();
    const isToday = data.date &&
      data.date.d === now.getDate() &&
      data.date.m === now.getMonth() &&
      data.date.y === now.getFullYear();
    const minMinutes = now.getHours() * 60 + now.getMinutes() + 120;
    const keep = (slot) => {
      return !isToday || _slotStartMinutes(slot) >= minMinutes;
    };
    const grouped = { morning: [], afternoon: [], evening: [] };
    (slots || []).filter(keep).forEach((slot) => {
      const start = _slotStartMinutes(slot);
      if (start < 12 * 60) grouped.morning.push(slot);
      else if (start < 17 * 60) grouped.afternoon.push(slot);
      else grouped.evening.push(slot);
    });
    return grouped;
  }, [data.date, slots]);
  const empty = !groupedSlots.morning.length && !groupedSlots.afternoon.length && !groupedSlots.evening.length;
  return (
    <>
      <div className="px-20 col gap-6 mb-12">
        <div className="t-h1">{t.chooseTime}</div>
        <div className="t-muted">
          {data.date ? `${data.date.dow} ${data.date.d} ${t.months[data.date.m]}` : t.chooseTimeSub}
        </div>
      </div>
      <div className="px-16 col gap-16" style={{ paddingBottom: 100 }}>
        {empty && (
          <div className="card-soft text-center" style={{ padding: 20 }}>
            <div className="t-muted">Plus de créneaux aujourd'hui — choisissez une autre date.</div>
          </div>
        )}
        {Object.entries(groupedSlots).map(([part, list]) => {
          if (!list.length) return null;
          return (
            <div key={part} className="col gap-10">
              <div className="row gap-8">
                <div className="t-tiny" style={{
                  textTransform: 'uppercase', letterSpacing: '0.1em',
                  fontWeight: 700, color: 'var(--text-3)',
                }}>{t[part]}</div>
                <div style={{ flex: 1, height: 1, background: 'var(--border)' }}/>
              </div>
              <div className="row wrap gap-8">
                {list.map(slot => {
                  const sel = data.time === slot.id;
                  return (
                    <button key={slot.id}
                      onClick={() => patch({ time: slot.id })}
                      className="press"
                      style={{
                        width: 'calc(25% - 6px)',
                        padding: '12px 0', borderRadius: 12,
                        background: sel ? 'var(--primary)' : 'var(--surface)',
                        color: sel ? 'var(--primary-text)' : 'var(--text)',
                        border: `1px solid ${sel ? 'var(--primary)' : 'var(--border)'}`,
                        fontWeight: 700, fontSize: 14,
                        cursor: 'pointer',
                        fontFamily: 'var(--font-display)',
                        letterSpacing: '-0.01em',
                        boxShadow: sel
                          ? '0 8px 18px -8px color-mix(in srgb, var(--primary) 55%, transparent)'
                          : 'none',
                        transform: sel ? 'translateY(-1px)' : 'translateY(0)',
                        transition: 'background 0.18s var(--ease-soft), border-color 0.18s var(--ease-soft), color 0.18s var(--ease-soft), box-shadow 0.22s var(--ease-soft), transform 0.22s var(--ease-spring)',
                      }}>{slot.label}</button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <CtaDock>
        <Btn block lg disabled={!data.time} onClick={onNext}
          style={{ opacity: data.time ? 1 : 0.4 }}>{t.next}</Btn>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Note
// ─────────────────────────────────────────────────────────────
function NoteStep({ t, data, patch, onNext }) {
  const [enabled, setEnabled] = useS_b(!!data.note);
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.addNote}</div>
        <div className="t-muted">{t.addNoteSub}</div>
      </div>
      <div className="px-16 col gap-12" style={{ paddingBottom: 100 }}>
        {!enabled ? (
          <>
            <button onClick={() => setEnabled(true)} className="card" style={{
              padding: 16, display: 'flex', gap: 12, alignItems: 'center', textAlign: 'inherit',
            }}>
              <div style={{
                width: 48, height: 48, borderRadius: 14,
                background: 'var(--surface-2)', color: 'var(--text)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}><Icons.Note size={22}/></div>
              <div className="col flex-1 gap-2">
                <div style={{ fontWeight: 700, fontSize: 15 }}>{t.addNoteCta}</div>
                <div className="t-muted">{t.addNoteSub}</div>
              </div>
              <Icons.ChevronRight size={18} style={{ color: 'var(--text-3)' }}/>
            </button>
          </>
        ) : (
          <div className="card" style={{ padding: 14 }}>
            <textarea autoFocus className="input" rows={5}
              placeholder={t.notePh}
              value={data.note}
              onChange={(e) => patch({ note: e.target.value })}
              style={{ resize: 'none' }}/>
            <div className="t-tiny mt-8" style={{ textAlign: 'end' }}>{data.note.length}/200</div>
          </div>
        )}
      </div>
      <CtaDock>
        <div className="row gap-8">
          <Btn variant="soft" style={{ flex: 1 }} onClick={() => { patch({ note: '' }); onNext(); }}>
            {t.skipNote}
          </Btn>
          <Btn style={{ flex: 1 }} onClick={onNext}>{t.next}</Btn>
        </div>
      </CtaDock>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Recap
// ─────────────────────────────────────────────────────────────
function RecapStep({ t, lang, data, patch, totalPrice, categories, centers, slots, staffContact, onEdit, onCancel, onConfirm, showToast }) {
  const category = _findById(categories, data.category);
  const catLabel = _categoryLabel(t, category, data.category);
  const centerLabel = _centerLabel(centers, data.centerId);
  const slotLabel = _slotLabel(slots, data.time);
  const promoLabel = data.promoCode ? data.promoCode : '';
  const phoneDigits = data.phone.replace(/\s/g, '').length;
  const phoneValid = phoneDigits >= 9;
  const [submitting, setSubmitting] = useS_b(false);
  const confirm = async () => {
    if (submitting) return;
    if (window.EwashLog) {
      window.EwashLog.hash(data.phone).then((phone_hash) => {
        window.EwashLog.info('booking.confirm', {
          phone_hash,
          category: data.category,
          service: data.service && data.service.id,
          total_dh: totalPrice,
          has_promo: !!data.promoApplied,
          addon_count: data.addons.length,
          client_request_id: data.clientRequestId || '',
        });
      }).catch(() => {
        window.EwashLog.warn('booking.error', { step: 'recap', error_code: 'phone_hash_failed' });
      });
    }
    setSubmitting(true);
    try {
      await onConfirm();
    } catch (err) {
      if (window.EwashLog) {
        window.EwashLog.warn('booking.error', {
          step: 'submit',
          error_code: (err && err.error_code) || 'booking_submit_failed',
          status: err && err.status,
        });
      }
      if (showToast) showToast(_submitErrorMessage(t, err));
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="t-h1">{t.recap}</div>
        <div className="t-muted">{t.recapSub}</div>
      </div>
      <div className="px-16 col gap-12" style={{ paddingBottom: 100 }}>
        <div className="card card-elev" style={{ padding: 0, overflow: 'hidden' }}>
          <PhoneRecapRow t={t} value={data.phone}
            onChange={(v) => patch({ phone: v.replace(/[^\d ]/g, '') })}/>
          <RecapRow icon={_isMotoCategory(data.category) ? <Icons.Moto size={18}/> : <Icons.Car size={18}/>}
            label={t.vehicle}
            value={_isMotoCategory(data.category) ? t.catMoto : `${catLabel}${data.make ? ' · ' + data.make : ''}${data.color ? ' · ' + data.color : ''}`}/>
          <RecapRow icon={<Icons.Pin size={18}/>} label={t.location}
            value={data.locationKind === 'home'
              ? data.pinAddress
              : centerLabel}/>
          <RecapRow icon={<Icons.Sparkle size={18}/>} label={t.service}
            value={data.service?.name}/>
          <RecapRow icon={<Icons.Calendar size={18}/>} label={t.dateTime}
            value={data.date ? `${data.date.dow} ${data.date.d} ${t.months[data.date.m]} · ${slotLabel}` : ''}/>
          {data.note && (
            <RecapRow icon={<Icons.Note size={18}/>} label={t.note} value={data.note} multiline/>
          )}
          {data.promoApplied && (
            <RecapRow icon={<Icons.Tag size={18}/>} label={t.promo}
              value={<span style={{ color: 'var(--accent-soft-text)', fontWeight: 700 }}>{promoLabel}</span>}/>
          )}
        </div>

        {/* Total card */}
        <div className="card" style={{
          background: 'var(--primary-soft)',
          borderColor: 'transparent', padding: '18px 18px 16px',
          boxShadow: '0 12px 28px -12px color-mix(in srgb, var(--primary) 35%, transparent)',
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute', insetInlineEnd: -20, top: -30,
            width: 120, height: 120, borderRadius: '50%',
            background: 'radial-gradient(circle, color-mix(in srgb, var(--primary) 14%, transparent) 0%, transparent 70%)',
            pointerEvents: 'none',
          }}/>
          <div className="row between" style={{ alignItems: 'baseline', position: 'relative' }}>
            <div className="col">
              <div className="t-tiny" style={{ fontWeight: 700, color: 'var(--primary-soft-text)', opacity: 0.7, letterSpacing: '0.08em', textTransform: 'uppercase' }}>{t.total}</div>
              <div className="t-num" style={{ fontWeight: 800, fontSize: 34, color: 'var(--primary-soft-text)', letterSpacing: '-0.025em', lineHeight: 1.05, marginTop: 2 }}>
                {totalPrice}<span style={{ fontSize: 15, marginInlineStart: 4, fontWeight: 700 }}>DH</span>
              </div>
            </div>
            <div className="t-tiny" style={{ textAlign: 'end', color: 'var(--primary-soft-text)', opacity: 0.78, maxWidth: 140, lineHeight: 1.4 }}>
              <Icons.Wallet size={14} style={{ verticalAlign: '-2px', marginInlineEnd: 4 }}/>
              {t.paymentCashSub}
            </div>
          </div>
        </div>

        <button onClick={onEdit} className="card-soft" style={{
          padding: 12, fontWeight: 600, fontSize: 13.5, color: 'var(--text-2)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          borderRadius: 14,
        }}>
          <Icons.Edit size={14}/> {t.edit}
        </button>
      </div>
      <CtaDock hint={!phoneValid ? t.phoneRecapHint : undefined}>
        <Btn block lg onClick={confirm} disabled={!phoneValid || submitting}
          style={{ opacity: (phoneValid && !submitting) ? 1 : 0.4 }}
          icon={<Icons.Check size={20} stroke={2.5}/>}>
          {submitting ? (t.submittingBooking || t.confirmBooking) : t.confirmBooking}
        </Btn>
      </CtaDock>
    </>
  );
}

// Phone-entry row inside the recap card. Replaces the old OTP login —
// we collect the number here, at the moment it actually matters.
function PhoneRecapRow({ t, value, onChange }) {
  return (
    <div style={{
      display: 'flex', gap: 12, padding: '14px 16px',
      borderBottom: '1px solid var(--border)',
      alignItems: 'center',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 10,
        background: 'var(--primary-soft)', color: 'var(--primary-soft-text)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <Icons.Phone size={18}/>
      </div>
      <div className="col flex-1" style={{ gap: 4, minWidth: 0 }}>
        <div className="t-tiny" style={{ fontWeight: 600, color: 'var(--text-2)' }}>{t.enterPhone}</div>
        <div className="row gap-6" style={{ alignItems: 'center' }}>
          <span style={{ fontSize: 15 }}>🇲🇦</span>
          <span style={{ fontWeight: 700, fontSize: 14 }}>+212</span>
          <input
            value={value}
            inputMode="numeric"
            placeholder="6 11 20 45 02"
            onChange={(e) => onChange(e.target.value)}
            style={{
              flex: 1, minWidth: 0,
              fontWeight: 600, fontSize: 14, letterSpacing: '0.3px',
              background: 'transparent', border: 'none', outline: 'none', padding: 0,
              color: 'var(--text)',
              fontFamily: 'var(--font-display)',
            }}/>
        </div>
      </div>
    </div>
  );
}

function RecapRow({ icon, label, value, multiline }) {
  return (
    <div style={{
      display: 'flex', gap: 12, padding: '14px 16px',
      borderBottom: '1px solid var(--border)',
      alignItems: multiline ? 'flex-start' : 'center',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 10,
        background: 'var(--surface-2)', color: 'var(--text)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>{icon}</div>
      <div className="col flex-1" style={{ gap: 2, minWidth: 0 }}>
        <div className="t-tiny" style={{ fontWeight: 600, color: 'var(--text-2)' }}>{label}</div>
        <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.4, wordBreak: 'break-word' }}>{value}</div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Confirmed (with addon offer)
// ─────────────────────────────────────────────────────────────
function ConfirmedStep({ t, lang, data, totalPrice, confirmedRef, confirmedTotal, variant, centers, slots, addons, staffContact, onAddons, onDone }) {
  const ref = confirmedRef || '';
  const displayedTotal = confirmedTotal == null ? totalPrice : confirmedTotal;
  const centerLabel = _centerLabel(centers, data.centerId);
  const slotLabel = _slotLabel(slots, data.time);
  useE_b(() => {
    if (!ref) return;
    if (!window.EwashLog) return;
    window.EwashLog.info('booking.confirmed', {
      ref,
      total_dh: displayedTotal,
      token_changed: false,
      duration_ms: 0,
    });
  }, [ref, displayedTotal]);
  // Auto-open the upsell modal after a brief beat so the user sees the
  // confirmation first. Dismissable only via the two CTAs inside it.
  const [offerOpen, setOfferOpen] = useS_b(false);
  useE_b(() => {
    if (_isMotoCategory(data.category) || !addons.length) return;
    const id = setTimeout(() => setOfferOpen(true), 800);
    return () => clearTimeout(id);
  }, [data.category, addons.length]);
  return (
    <div className="col anim-fade" style={{ paddingBottom: 12 }}>
      {/* Confirmation hero */}
      <div style={{
        background: 'var(--hero-grad)',
        padding: '36px 24px 40px',
        color: '#fff',
        position: 'relative', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', inset: 0,
          background: 'radial-gradient(600px 200px at 50% 0%, rgba(255,255,255,0.18), transparent 60%)',
          pointerEvents: 'none',
        }}/>
        <div style={{
          width: 80, height: 80, borderRadius: 99,
          background: 'rgba(255,255,255,0.16)',
          border: '2px solid rgba(255,255,255,0.35)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          marginInline: 'auto', marginBottom: 16,
          position: 'relative', zIndex: 1,
          animation: 'confirmedPop 0.6s var(--ease-spring)',
          boxShadow: '0 8px 32px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.3)',
        }}>
          <Icons.Check size={42} stroke={2.8}/>
        </div>
        <div style={{
          fontFamily: 'var(--font-display)', fontWeight: 800,
          fontSize: 26, textAlign: 'center', letterSpacing: '-0.025em',
          position: 'relative', zIndex: 1, lineHeight: 1.1,
        }}>{t.bookingConfirmed}</div>
        <div style={{
          textAlign: 'center', fontSize: 14,
          color: 'rgba(255,255,255,0.78)', marginTop: 8,
          position: 'relative', zIndex: 1, lineHeight: 1.45,
          maxWidth: 280, marginInline: 'auto',
        }}>{t.confirmedSub}</div>
        <div className="t-tiny" style={{
          textAlign: 'center', marginTop: 14,
          letterSpacing: '0.14em', fontWeight: 700,
          color: 'rgba(255,255,255,0.7)',
          position: 'relative', zIndex: 1,
        }}>{t.bookingRef.toUpperCase()} · {ref}</div>
        {/* ambient ripples */}
        {[1,2,3].map(i => (
          <div key={i} style={{
            position: 'absolute', left: '50%', top: 66,
            transform: 'translate(-50%, 0)',
            width: 80, height: 80, borderRadius: 99,
            border: '2px solid rgba(255,255,255,0.35)',
            animation: `ripple 2.8s ease-out infinite ${i * 0.5}s`,
            pointerEvents: 'none',
          }}/>
        ))}
      </div>

      <div className="px-16 col gap-16 mt-16">
        {/* Quick recap chip */}
        <div className="card" style={{ padding: 14 }}>
          <div className="row gap-12">
            <div style={{
              width: 48, minWidth: 48, borderRadius: 12,
              background: 'var(--primary-soft)', color: 'var(--primary-soft-text)',
              padding: '6px 0', textAlign: 'center',
            }}>
              <div className="t-tiny" style={{ fontWeight: 700, opacity: 0.9 }}>{t.days[(data.date?.d || 0) % 7]?.toUpperCase()}</div>
              <div className="t-num" style={{ fontWeight: 800, fontSize: 18, lineHeight: 1.1 }}>{data.date?.d}</div>
              <div className="t-tiny" style={{ opacity: 0.9 }}>{t.months[data.date?.m]?.toUpperCase()}</div>
            </div>
            <div className="col gap-2 flex-1">
              <div style={{ fontWeight: 700, fontSize: 14.5 }}>{data.service?.name}</div>
              <div className="t-muted" style={{ fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 5 }}>
                <Icons.Clock size={12}/> {slotLabel} · {data.service?.durationMin} {t.min}
              </div>
              <div className="t-muted" style={{ fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 5 }}>
                <Icons.Pin size={12}/> {data.locationKind === 'home' ? data.pinAddress : centerLabel}
              </div>
            </div>
            <div className="col" style={{ alignItems: 'flex-end', textAlign: 'end' }}>
              <div className="t-tiny" style={{ color: 'var(--text-3)', fontWeight: 600 }}>{t.total}</div>
              <div className="t-num" style={{ fontWeight: 800, fontSize: 18 }}>{displayedTotal}<span style={{ fontSize: 10, marginInlineStart: 2 }}>DH</span></div>
            </div>
          </div>
        </div>

        <button className="card-soft" style={{
          padding: 14, display: 'flex', gap: 10,
          alignItems: 'center', justifyContent: 'center',
          fontWeight: 600, fontSize: 13.5,
          color: 'var(--text)', borderRadius: 14,
        }}>
          <Icons.Calendar size={18}/> {t.addToCalendar}
        </button>

        <Btn variant="ghost" block onClick={onDone}>
          {lang === 'ar' ? 'العودة إلى الرئيسية' : 'Retour à l\'accueil'}
        </Btn>
      </div>

      {offerOpen && !_isMotoCategory(data.category) && (
        <OfferSheet
          t={t} variant={variant} addons={addons}
          onDecline={() => setOfferOpen(false)}
          onAccept={() => { setOfferOpen(false); onAddons(); }}/>
      )}
    </div>
  );
}

// Add-on upsell as an auto-opening bottom sheet. Backdrop click is a no-op —
// the user has to tap Non merci or Voir l'offre to dismiss it.
function OfferSheet({ t, variant, addons, onDecline, onAccept }) {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      background: 'rgba(14,42,42,0.55)',
      display: 'flex', alignItems: 'flex-end',
      zIndex: 60,
      animation: 'fadeIn 0.25s ease',
    }}>
      <div style={{
        width: '100%',
        background: variant === 'premium'
          ? 'linear-gradient(135deg, #2a2317 0%, #4a3e22 100%)'
          : 'linear-gradient(135deg, #84C42B 0%, #5E9412 100%)',
        color: variant === 'premium' ? '#F5E9CC' : '#0E1A0A',
        borderRadius: '28px 28px 0 0',
        padding: '14px 20px 22px',
        position: 'relative',
        overflow: 'hidden',
        animation: 'sheetUp 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)',
        boxShadow: '0 -20px 60px rgba(0,0,0,0.35)',
      }}>
        {/* Grabber */}
        <div style={{
          width: 44, height: 4, borderRadius: 2,
          background: variant === 'premium' ? 'rgba(245,233,204,0.4)' : 'rgba(14,26,10,0.25)',
          margin: '0 auto 16px',
        }}/>

        {/* Service add-on marker */}
        <div style={{
          position: 'absolute',
          top: 20, insetInlineEnd: -16,
          width: 108, height: 108,
          borderRadius: '50%',
          background: variant === 'premium' ? 'var(--gold)' : '#fff',
          color: variant === 'premium' ? '#0a0a0a' : '#5E9412',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transform: 'rotate(10deg)',
          boxShadow: '0 8px 20px rgba(0,0,0,0.22)',
          fontFamily: 'var(--font-display)',
          fontWeight: 800, fontSize: 24,
          letterSpacing: '-0.02em',
          pointerEvents: 'none',
        }}><Icons.Sparkle size={42}/></div>

        <div style={{ maxWidth: 'calc(100% - 90px)', position: 'relative', marginBottom: 14 }}>
          <div className="t-tiny" style={{
            fontWeight: 700, letterSpacing: '0.12em',
            opacity: 0.75, marginBottom: 6,
          }}>✦ {t.addonOffer.toUpperCase()}</div>
          <div style={{
            fontFamily: 'var(--font-display)', fontWeight: 800,
            fontSize: 24, lineHeight: 1.1, letterSpacing: '-0.02em',
          }}>Ajoutez de l'esthétique à votre lavage</div>
        </div>

        <div style={{
          fontSize: 14, lineHeight: 1.45, fontWeight: 500,
          marginBottom: 14, opacity: 0.92,
          position: 'relative',
        }}>{t.addonOfferSub}</div>

        <div className="col gap-8" style={{
          background: variant === 'premium' ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.28)',
          borderRadius: 14, padding: '12px 14px', marginBottom: 18,
          position: 'relative',
        }}>
          {addons.slice(0, 3).map((a) => (
            <div key={a.id} className="row between" style={{ alignItems: 'baseline' }}>
              <span style={{ fontSize: 13.5, fontWeight: 600 }}>{a.name}</span>
              <div className="row gap-6" style={{ alignItems: 'baseline' }}>
                <span className="t-num" style={{ fontWeight: 800, fontSize: 15.5 }}>
                  {_addonPreviewPrice(a)} DH
                </span>
                <span style={{ fontSize: 10.5, opacity: 0.7, textDecoration: 'line-through' }}>
                  {a.price_dh}
                </span>
              </div>
            </div>
          ))}
        </div>

        <button onClick={onAccept} style={{
          width: '100%',
          padding: '15px 22px',
          borderRadius: 999,
          background: variant === 'premium' ? 'var(--gold)' : '#0E1A0A',
          color: variant === 'premium' ? '#0a0a0a' : '#FFFFFF',
          fontWeight: 700, fontSize: 16,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          position: 'relative',
          boxShadow: '0 4px 14px -2px rgba(0,0,0,0.25)',
          cursor: 'pointer',
        }}>
          {t.seeOffer}
          <Icons.ChevronRight size={20} stroke={2.5}/>
        </button>

        <button onClick={onDecline} style={{
          width: '100%',
          padding: '14px 0 0',
          background: 'transparent',
          color: 'inherit',
          opacity: 0.75,
          fontWeight: 600, fontSize: 14,
          cursor: 'pointer',
          position: 'relative',
        }}>{t.skipOffer}</button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP: Add-ons
// ─────────────────────────────────────────────────────────────
function AddonsStep({ t, data, patch, addons, totalPrice, onDone }) {
  const toggle = (id) => {
    const next = data.addons.includes(id)
      ? data.addons.filter(x => x !== id)
      : [...data.addons, id];
    patch({ addons: next });
  };
  return (
    <>
      <div className="px-20 col gap-6 mb-16">
        <div className="row gap-8" style={{ alignItems: 'center' }}>
          <div className="t-h1">{t.addonsTitle}</div>
        </div>
        <div className="t-muted">{t.addonsSub}</div>
      </div>
      <div className="px-16 col gap-10" style={{ paddingBottom: 100 }}>
        {addons.map(a => {
          const sel = data.addons.includes(a.id);
          const previewPrice = _addonPreviewPrice(a);
          return (
            <button key={a.id} onClick={() => toggle(a.id)}
              className={`svc-card ${sel ? 'selected' : ''}`}
              style={{ textAlign: 'inherit', padding: 14 }}>
              <div className="thumb" style={{
                background: sel ? 'var(--primary)' : 'var(--accent-soft)',
                color: sel ? 'var(--primary-text)' : 'var(--accent-soft-text)',
              }}>
                <Icons.Sparkle size={26}/>
              </div>
              <div className="col gap-4 flex-1">
                <div style={{ fontWeight: 700, fontSize: 14.5 }}>{a.name}</div>
                <div className="t-muted" style={{ fontSize: 12.5 }}>{a.desc}</div>
                <div className="row gap-6 mt-4" style={{ alignItems: 'baseline' }}>
                  <span className="t-num" style={{ fontWeight: 800, fontSize: 15, color: 'var(--accent-soft-text)' }}>{previewPrice}</span>
                  <span className="t-tiny" style={{ color: 'var(--text-2)' }}>DH</span>
                  <span style={{ fontSize: 10.5, color: 'var(--text-3)', textDecoration: 'line-through' }}>
                    {a.price_dh}
                  </span>
                </div>
              </div>
              <div className="center" style={{ width: 28, alignSelf: 'center' }}>
                <div style={{
                  width: 26, height: 26, borderRadius: 8,
                  border: `2px solid ${sel ? 'var(--primary)' : 'var(--border-strong)'}`,
                  background: sel ? 'var(--primary)' : 'transparent',
                  color: 'var(--primary-text)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {sel && <Icons.Check size={15} stroke={3}/>}
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <CtaDock>
        <div className="row between mb-8" style={{ paddingInline: 4 }}>
          <span className="t-muted" style={{ fontSize: 13 }}>{t.total}</span>
          <span className="t-num" style={{ fontWeight: 800, fontSize: 18 }}>{totalPrice}<span style={{ fontSize: 11, marginInlineStart: 4, color: 'var(--text-2)' }}>DH</span></span>
        </div>
        <Btn block lg onClick={onDone}>
          {data.addons.length > 0 ? t.addToBooking : t.skipOffer}
        </Btn>
      </CtaDock>
    </>
  );
}

window.BookingFlow = BookingFlow;
