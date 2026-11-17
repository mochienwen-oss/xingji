import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { useDraft } from '../app/providers/DraftProvider';
import { useSession } from '../app/providers/SessionProvider';
import { useToast } from '../app/providers/ToastProvider';
import { useHashRoute } from '../app/routing/useHashRoute';
import { BrandMark } from '../components/BrandMark';
import { CityChips } from '../components/explore/CityChips';
import { Composer } from '../components/explore/Composer';
import { Conversation } from '../components/explore/Conversation';
import { ExploreMap, type ExploreCenter } from '../components/explore/ExploreMap';
import { NearbyGrid } from '../components/explore/NearbyGrid';
import { PlaceDetailSheet } from '../components/explore/PlaceDetailSheet';
import { PreviewSheet } from '../components/explore/PreviewSheet';
import { SavedPlacesList } from '../components/explore/SavedPlacesList';
import { StartHereCard } from '../components/explore/StartHereCard';
import { Avatar } from '../components/ui/Avatar';
import { Button } from '../components/ui/Button';
import { IconButton } from '../components/ui/IconButton';
import { Kicker } from '../components/ui/Kicker';
import { Sheet } from '../components/ui/Sheet';
import { cx } from '../components/ui/cx';
import { LocateIcon } from '../components/icons';
import { openAuth } from '../lib/auth-events';
import { api, message } from '../lib/api';
import { usePlanningSession } from '../lib/harness/usePlanningSession';
import type { HarnessSummary } from '../lib/harness/session';
import type { SheetDetent } from '../lib/useSheetDrag';
import type { Day, Place, Stop, Trip, TripMapView } from '../types/trip';
import styles from './ExplorePage.module.css';

// 城市池：一次只露一批，「换一批」轮换，探索入口不再固定 6 城。
const CITY_POOL = [
  '杭州', '成都', '西安', '大理', '厦门', '泉州',
  '苏州', '南京', '重庆', '长沙', '昆明', '青岛',
  '北京', '上海', '广州', '深圳', '武汉', '桂林',
];
const CITY_BATCH_SIZE = 8;
const NEARBY_RADIUS = 3000;
const MAX_SAME_CITY_PLACES = 20;
const MAX_SAVED_PLACES = 60;
const MAX_FIRST_DAY_STOPS = 12;

type CityCenter = { lon: number; lat: number; city: string };

function isInPreview(preview: Trip | null, placeId: string): boolean {
  if (!preview) return false;
  return preview.days.some((day) => day.stops.some((stop) => stop.place.id === placeId));
}

function GenerateErrorCard({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return (
    <div className={styles.aiError} role="alert">
      <div>
        <p className={styles.aiErrorTitle}>这次没生成成功</p>
        <p className={styles.aiErrorText}>{detail || '可以换个说法，或者少选几个条件再试一次。'}</p>
      </div>
      <Button variant="secondary" onClick={onRetry}>重试</Button>
    </div>
  );
}

export function ExplorePage() {
  const {
    form, messages, places, setForm, setMessages, updatePlaces, clearDraft,
    summary, turnCount, setHarness,
  } = useDraft();
  const { user } = useSession();
  const { toast } = useToast();
  const { navigate } = useHashRoute();

  const [detent, setDetent] = useState<SheetDetent>('half');
  const [center, setCenter] = useState<ExploreCenter | null>(null);
  const [nearby, setNearby] = useState<Place[]>([]);
  const [nearbyLoading, setNearbyLoading] = useState(false);
  const [nearbyError, setNearbyError] = useState('');
  const [nearbyToken, setNearbyToken] = useState(0);
  const [cityLoading, setCityLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ place: Place; token: number } | null>(null);
  const [locateToken, setLocateToken] = useState(0);
  const [input, setInput] = useState('');
  const [harnessPlaces, setHarnessPlaces] = useState<Place[]>([]);
  const [aiError, setAiError] = useState('');
  const [preview, setPreview] = useState<Trip | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [detailPlace, setDetailPlace] = useState<Place | null>(null);
  const [citySeed, setCitySeed] = useState(0);

  const autoCityRef = useRef(false);
  const cityAbortRef = useRef<AbortController | null>(null);

  const activeCity = (center?.city || form.city || '').trim();
  const selectedCity = CITY_POOL.find(
    (city) => activeCity === city || activeCity === `${city}市`,
  ) ?? '';
  const cityBatch = useMemo(() => {
    const rotate = citySeed % CITY_POOL.length;
    const rotated = [...CITY_POOL.slice(rotate), ...CITY_POOL.slice(0, rotate)];
    const rest = rotated.filter((city) => city !== selectedCity).slice(
      0,
      CITY_BATCH_SIZE - (selectedCity ? 1 : 0),
    );
    return selectedCity ? [selectedCity, ...rest] : rest;
  }, [citySeed, selectedCity]);
  const savedIds = useMemo(() => new Set(places.map((place) => place.id)), [places]);
  const previewPlaceIds = useMemo(() => {
    const ids = new Set<string>();
    for (const day of preview?.days ?? []) {
      for (const stop of day.stops) ids.add(stop.place.id);
    }
    return ids;
  }, [preview]);
  const previewMap = useMemo<TripMapView | null>(() => (
    preview
      ? {
        tripId: preview.id,
        previewKey: preview.created_at || String(preview.days.length),
        days: preview.days,
        backlog: preview.backlog ?? [],
        showBacklog: false,
        focusPlace: null,
      }
      : null
  ), [preview]);

  const loadCity = useCallback(async (raw: string) => {
    const city = raw.trim();
    if (!city) return;
    autoCityRef.current = true;
    cityAbortRef.current?.abort();
    const controller = new AbortController();
    cityAbortRef.current = controller;
    setCityLoading(true);
    setHarnessPlaces([]);
    try {
      const found = await api<CityCenter>(
        `/discover/city-center?city=${encodeURIComponent(city)}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setCenter({
        lon: found.lon,
        lat: found.lat,
        city: found.city,
        label: found.city,
        located: false,
      });
      setForm((current) => (
        current.city === found.city ? current : { ...current, city: found.city }
      ));
    } catch (error) {
      if (controller.signal.aborted) return;
      toast(message(error), 'error');
    } finally {
      if (!controller.signal.aborted) setCityLoading(false);
    }
  }, [setForm, toast]);

  // 草稿里已有城市时，只在进入页面后加载一次；定位和城市 chip 会自行置位。
  useEffect(() => {
    if (autoCityRef.current) return;
    const city = form.city.trim();
    if (!city) return;
    void loadCity(city);
  }, [form.city, loadCity]);

  useEffect(() => () => {
    cityAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!center) {
      setNearby([]);
      setNearbyError('');
      setNearbyLoading(false);
      return;
    }
    const controller = new AbortController();
    setNearbyLoading(true);
    setNearbyError('');
    void api<Place[]>(
      `/discover/nearby?lon=${center.lon}&lat=${center.lat}&radius=${NEARBY_RADIUS}`,
      { signal: controller.signal },
    ).then((found) => {
      if (controller.signal.aborted) return;
      setNearby(found);
      setSelectedId(found[0]?.id ?? null);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setNearby([]);
      setNearbyError(message(error));
    }).finally(() => {
      if (!controller.signal.aborted) setNearbyLoading(false);
    });
    return () => controller.abort();
  }, [center, nearbyToken]);

  const handleLocated = useCallback((value: ExploreCenter) => {
    autoCityRef.current = true;
    setCenter(value);
    setSelectedId(null);
    setForm((current) => (
      current.city.trim() ? current : { ...current, city: value.city }
    ));
  }, [setForm]);

  const handleLocationError = useCallback((reason: string) => {
    toast(reason || '定位失败，请检查定位权限后重试。', 'error');
  }, [toast]);

  const openPlace = useCallback((place: Place) => {
    setSelectedId(place.id);
    setFocus((current) => ({ place, token: (current?.token ?? 0) + 1 }));
    setDetailPlace(place);
  }, []);

  const handleMapSelect = useCallback((place: Place) => {
    setSelectedId(place.id);
    setDetailPlace(place);
  }, []);

  const planning = usePlanningSession({
    onFormPatch: (patch) => {
      setForm((current) => ({ ...current, ...patch }));
      const city = typeof patch.city === 'string' ? patch.city.trim() : '';
      if (city && city !== activeCity) void loadCity(city);
    },
    onPlan: (trip) => {
      setPreview(trip);
      // 不再自动打开全屏预览：半屏结果卡 + 地图渐进画线先出现，「查看全部」再进详情。
      setHarnessPlaces([]);
      toast('路线已生成，正在地图上画线', 'success');
      const city = trip.request?.city?.trim();
      if (city) {
        setForm((current) => (current.city === city ? current : { ...current, city }));
      }
    },
    onAssistant: (text) => {
      setMessages((current) => [...current, { role: 'assistant', content: text }]);
    },
    onQuestion: () => undefined,
    onPlaces: (found) => {
      if (found.length) setHarnessPlaces(found);
    },
    onError: (detail) => {
      setAiError(detail);
      toast(detail, 'error');
    },
    onMeta: (meta) => {
      setHarness({
        summary: meta.summary === undefined
          ? undefined
          : meta.summary as Record<string, unknown> | null,
        turnCount: meta.turnCount,
      });
    },
  });
  const generating = planning.running;

  const sendTurn = useCallback((raw: string): boolean => {
    const content = raw.trim();
    if (!content) return false;
    if (planning.running) {
      toast('上一条还在处理，稍等一下。', 'info');
      return false;
    }
    const nextMessages = [...messages, { role: 'user' as const, content }];
    setMessages(nextMessages);
    setInput('');
    setAiError('');
    setSaveError('');
    // 生成期间保持地图可见：peek 抬到半屏，半屏/全屏尊重用户当前选择。
    setDetent((current) => (current === 'peek' ? 'half' : current));
    return planning.send({
      mode: preview ? 'preview' : 'explore',
      message: content,
      messages: nextMessages.slice(-40),
      form: { ...form, city: activeCity },
      places,
      summary: (summary as HarnessSummary | null) ?? null,
      turnCount,
      preview: preview ?? null,
    });
  }, [activeCity, form, messages, places, planning, preview, setMessages, summary, toast, turnCount]);

  const submitMessage = () => {
    void sendTurn(input);
  };

  const generate = () => {
    if (planning.running) return;
    void sendTurn(input.trim() || '帮我按现在的条件生成一版行程。');
  };

  const collect = useCallback((place: Place): string => {
    const adding = !places.some((item) => item.id === place.id);
    const city = (place.city || center?.city || form.city || '').trim();
    if (adding) {
      const sameCityCount = places.filter(
        (item) => (item.city || '').trim() === city,
      ).length;
      if (sameCityCount >= MAX_SAME_CITY_PLACES) {
        const reason = `「${city || '未标注城市'}」最多收藏 ${MAX_SAME_CITY_PLACES} 个待规划地点`;
        toast(reason, 'error');
        return reason;
      }
      if (places.length >= MAX_SAVED_PLACES) {
        const reason = `最多收藏 ${MAX_SAVED_PLACES} 个待规划地点`;
        toast(reason, 'error');
        return reason;
      }
    }
    const reason = updatePlaces((current) => (
      current.some((item) => item.id === place.id)
        ? current.filter((item) => item.id !== place.id)
        : [...current, { ...place, city }]
    ));
    if (reason) {
      toast(reason, 'error');
      return reason;
    }
    toast(adding ? `已收藏 ${place.name}` : `已取消收藏 ${place.name}`, 'success');
    return '';
  }, [center?.city, form.city, places, toast, updatePlaces]);

  const addToPreview = useCallback((place: Place) => {
    if (!preview) {
      toast('先生成一条预览路线，再把地点加进行程。', 'info');
      return;
    }
    if (isInPreview(preview, place.id)) {
      toast('这个地点已经在预览路线里了。', 'info');
      return;
    }
    const baseDays: Day[] = preview.days.length
      ? preview.days
      : [{ stops: [], routes: [] }];
    if (baseDays[0].stops.length >= MAX_FIRST_DAY_STOPS) {
      toast(`第一天已经排满 ${MAX_FIRST_DAY_STOPS} 站，先删掉一个地点再试。`, 'error');
      return;
    }
    const stop: Stop = {
      place,
      duration: 90,
      reason: '从附近加入，顺路安排',
    };
    const days = baseDays.map((day, index) => (
      index === 0 ? { ...day, stops: [...day.stops, stop] } : day
    ));
    setPreview({ ...preview, days });
    toast(`已把 ${place.name} 加到预览第 1 天`, 'success');
  }, [preview, toast]);

  const savePreview = async () => {
    if (!preview || saving) return;
    if (!user) {
      toast('登录后才能保存行程，登录后再点一次「保存行程」。', 'info');
      openAuth('save');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const trip = await api<Trip>('/trips/from-preview', {
        method: 'POST',
        timeoutMs: 120000,
        body: JSON.stringify({
          request: preview.request,
          days: preview.days,
          backlog: preview.backlog ?? [],
          conversation: messages.slice(-100),
        }),
      });
      clearDraft();
      setPreview(null);
      setPreviewOpen(false);
      toast('行程已保存', 'success');
      navigate(`/trips/${trip.id}`);
    } catch (error) {
      const reason = message(error);
      setSaveError(reason);
      toast(reason, 'error');
    } finally {
      setSaving(false);
    }
  };

  const previewError = saveError || (
    preview && !user
      ? '登录后才能保存行程；登录后请再点一次「保存行程」。'
      : ''
  );

  const nearbyPlaces = detent === 'full' ? nearby : nearby.slice(0, 6);

  // 地图署名按抽屉档位让位：peek/half 贴在抽屉上沿，full 时整块让出（署名随地图被抽屉覆盖）。
  const sheetHeight = detent === 'peek' ? '112px' : detent === 'half' ? '46dvh' : '100dvh';

  return (
    <main className={styles.page} style={{ '--sheet-height': sheetHeight } as CSSProperties}>
      <div className={styles.mapArea}>
        <ExploreMap
          center={center}
          places={preview ? [] : (harnessPlaces.length ? harnessPlaces : nearby)}
          selectedId={selectedId}
          tripView={previewMap}
          focus={focus}
          locateToken={locateToken}
          onLocated={handleLocated}
          onLocationError={handleLocationError}
          onSelect={handleMapSelect}
        />
      </div>

      <header className={styles.topBar}>
        <div className={styles.topLeft}>
          <div className={styles.brand}>
            <BrandMark />
            <h1 className={styles.wordmark}>行迹</h1>
            <span className={styles.wordmarkEn} aria-hidden="true">TRIP</span>
          </div>
        </div>
        <div className={styles.topActions}>
          <IconButton
            className={styles.locate}
            label="定位到当前位置"
            onClick={() => setLocateToken((token) => token + 1)}
          >
            <LocateIcon size={20} />
          </IconButton>
          {user ? (
            <button
              type="button"
              className={cx(styles.avatarButton, styles.accountAction)}
              aria-label="打开个人中心"
              onClick={() => navigate('/profile')}
            >
              <Avatar name={user.username} size="sm" />
            </button>
          ) : (
            <Button className={styles.accountAction} variant="secondary" onClick={() => openAuth('login')}>
              登录
            </Button>
          )}
        </div>
      </header>

      <div className={styles.sheetHost}>
        <Sheet
          open
          className={styles.mainSheet}
          detent={detent}
          onDetentChange={setDetent}
          labelledBy={detent === 'peek' ? 'explore-peek-title' : 'explore-sheet-title'}
        >
          {detent === 'peek' ? (
            <div className={styles.peek}>
              <div className={styles.peekLead}>
                <Kicker className={styles.kicker}>下一站</Kicker>
                <h2 id="explore-peek-title" className={styles.peekTitle}>附近有什么</h2>
              </div>
              {nearby.length ? (
                <div className={styles.peekRow} aria-label="附近地点预览">
                  {nearby.slice(0, 3).map((place) => (
                    <button
                      key={place.id}
                      type="button"
                      className={styles.peekCard}
                      aria-label={`查看${place.name}`}
                      onClick={() => openPlace(place)}
                    >
                      <span className={styles.peekName}>{place.name}</span>
                      <span className={styles.peekMeta}>
                        {place.city || place.address || '附近'}
                      </span>
                      {savedIds.has(place.id) ? (
                        <span className={styles.savedTag}>已收藏</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              ) : (
                <p className={styles.peekEmpty}>定位后显示附近</p>
              )}
            </div>
          ) : (
            <div className={cx(styles.sheetBody, detent === 'half' && styles.sheetBodyHalf)}>
              <div className={styles.sheetScroll}>
                <h2 id="explore-sheet-title" className={styles.sheetTitle}>
                  把想法变成一条路线
                </h2>
                <CityChips
                  cities={cityBatch}
                  selected={selectedCity}
                  loading={cityLoading}
                  onSelect={(city) => { void loadCity(city); }}
                  onRefresh={() => setCitySeed((seed) => seed + 1)}
                />
                {aiError ? <GenerateErrorCard detail={aiError} onRetry={() => { void generate(); }} /> : null}

                {detent === 'half' && generating && harnessPlaces.length ? (
                  <section className={styles.section} aria-label="路线生成进度">
                    <div className={styles.liveCard}>
                      <span className={styles.liveDot} aria-hidden="true" />
                      <p className={styles.liveStatus}>已在地图上标出 {harnessPlaces.length} 个候选地点</p>
                    </div>
                  </section>
                ) : null}

                {detent === 'half' && preview && !generating ? (
                  <section className={styles.section} aria-label="生成的路线">
                    <div className={styles.resultCard}>
                      <div className={styles.resultCopy}>
                        <p className={styles.resultTitle}>路线已生成</p>
                        <p className={styles.resultMeta}>
                          {activeCity} · {preview.days.length} 天 ·{' '}
                          {preview.days.reduce((total, day) => total + day.stops.length, 0)} 站
                        </p>
                        {previewError ? (
                          <p className={styles.resultError} role="alert">{previewError}</p>
                        ) : null}
                      </div>
                      <div className={styles.resultActions}>
                        <Button variant="secondary" onClick={() => setPreviewOpen(true)}>查看全部</Button>
                        <Button loading={saving} onClick={() => { void savePreview(); }}>保存行程</Button>
                      </div>
                    </div>
                  </section>
                ) : null}

                {detent === 'half' && (messages.length > 0 || generating) ? (
                  <section className={styles.section} aria-labelledby="explore-chat-half-title">
                    <div className={styles.sectionHead}>
                      <h3 id="explore-chat-half-title" className={styles.sectionTitle}>规划对话</h3>
                      <span className={styles.sectionMeta}>
                        {generating ? '正在生成' : `${messages.length} 条`}
                      </span>
                    </div>
                    <Conversation
                      messages={messages}
                      streaming={planning.streamText}
                      busy={generating}
                      status={planning.status || '正在理解需求…'}
                      onCancel={planning.cancel}
                    />
                  </section>
                ) : null}

                {detent === 'half' ? (
                  <>
                    <section className={styles.section} aria-labelledby="explore-nearby-title">
                      <div className={styles.sectionHead}>
                        <h3 id="explore-nearby-title" className={styles.sectionTitle}>附近</h3>
                        {activeCity ? (
                          <span className={styles.sectionMeta}>{activeCity}</span>
                        ) : null}
                      </div>
                      <NearbyGrid
                        places={nearbyPlaces}
                        loading={nearbyLoading}
                        error={nearbyError}
                        hasCenter={Boolean(center)}
                        onRetry={() => setNearbyToken((token) => token + 1)}
                        onSelect={openPlace}
                      />
                    </section>
                    <section className={styles.section} aria-labelledby="explore-saved-title">
                      <div className={styles.sectionHead}>
                        <h3 id="explore-saved-title" className={styles.sectionTitle}>收藏</h3>
                        <span className={styles.sectionMeta}>{places.length} 个</span>
                      </div>
                      <SavedPlacesList
                        places={places}
                        onSelect={openPlace}
                        onRemove={(place) => collect(place)}
                      />
                    </section>
                  </>
                ) : (
                  <>
                    {!center && places.length === 0 ? <StartHereCard /> : null}
                    <section className={styles.section} aria-labelledby="explore-chat-title">
                      <div className={styles.sectionHead}>
                        <h3 id="explore-chat-title" className={styles.sectionTitle}>规划对话</h3>
                        <span className={styles.sectionMeta}>
                          {generating ? '正在生成' : `${messages.length} 条`}
                        </span>
                      </div>
                      <Conversation
                        messages={messages}
                        streaming={planning.streamText}
                        busy={generating}
                        status={planning.status || '正在理解需求…'}
                        onCancel={planning.cancel}
                      />
                    </section>
                    <section className={styles.section} aria-labelledby="explore-nearby-full-title">
                      <div className={styles.sectionHead}>
                        <h3 id="explore-nearby-full-title" className={styles.sectionTitle}>附近</h3>
                        {activeCity ? (
                          <span className={styles.sectionMeta}>{activeCity}</span>
                        ) : null}
                      </div>
                      <NearbyGrid
                        places={nearbyPlaces}
                        loading={nearbyLoading}
                        error={nearbyError}
                        hasCenter={Boolean(center)}
                        onRetry={() => setNearbyToken((token) => token + 1)}
                        onSelect={openPlace}
                      />
                    </section>
                    <section className={styles.section} aria-labelledby="explore-saved-full-title">
                      <div className={styles.sectionHead}>
                        <h3 id="explore-saved-full-title" className={styles.sectionTitle}>收藏</h3>
                        <span className={styles.sectionMeta}>{places.length} 个</span>
                      </div>
                      <SavedPlacesList
                        places={places}
                        onSelect={openPlace}
                        onRemove={(place) => collect(place)}
                      />
                    </section>
                  </>
                )}
              </div>
              <div className={styles.composerDock}>
                <Composer
                  value={input}
                  onChange={setInput}
                  onSubmit={submitMessage}
                  onGenerate={generate}
                  canGenerate={Boolean(activeCity) && !preview}
                  generating={generating}
                  busy={generating}
                  city={activeCity}
                  hasPreview={Boolean(preview)}
                  onOpenPreview={() => setPreviewOpen(true)}
                />
              </div>
            </div>
          )}
        </Sheet>

        <PreviewSheet
          preview={preview}
          open={previewOpen && Boolean(preview)}
          saved={false}
          saving={saving}
          error={previewError}
          onClose={() => {
            setPreviewOpen(false);
            setSaveError('');
          }}
          onSave={() => { void savePreview(); }}
        />

        <PlaceDetailSheet
          place={detailPlace}
          open={Boolean(detailPlace)}
          saved={Boolean(detailPlace && previewPlaceIds.has(detailPlace.id))}
          collected={Boolean(detailPlace && savedIds.has(detailPlace.id))}
          onClose={() => setDetailPlace(null)}
          onAdd={(place) => addToPreview(place)}
          onToggle={(place) => collect(place)}
        />
      </div>
    </main>
  );
}