import { useId } from 'react';
import { coverGlyph, coverMotif, coverTone, type CoverMotif } from '../../lib/cover';
import { cx } from '../ui/cx';
import styles from './TripCover.module.css';

export type TripCoverProps = {
  city: string;
  /** 形如「11月5日–11月7日」，由调用方格式化，组件不猜日期。 */
  dateRange?: string;
  days?: number;
  size?: 'card' | 'hero' | 'thumb';
  /** 顶部 kicker，默认「行迹 · TRIP」；调用方可传入拼音/英文城市名。 */
  kicker?: string;
  className?: string;
};

/** 背景风景线稿：只画地方特征，不抢字徽。 */
function CoverScene({ motif }: { motif: CoverMotif }) {
  switch (motif) {
    case 'water':
      return (
        <g>
          <path className={styles.horizon} d="M34 50h66" />
          <path d="M36 54q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M38 58q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M41 62q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M44 47q 4 -7 12 0" />
          <path d="M44 47h16" />
          <circle cx="88" cy="18" r="4.2" />
          <path className={styles.rays} d="M88 11.5v2M88 22.5v2M81.5 18h2M92.5 18h2" />
        </g>
      );
    case 'mountain':
      return (
        <g>
          <path d="M34 59 L47 31 l8 13 l8 -17 l13 26 l6 -8 l9 14" />
          <path className={styles.secondary} d="M40 59 L51 38 l6 8 l8 -12 l8 18" />
          <path className={styles.horizon} d="M34 61h66" />
          <path className={styles.mist} d="M36 47h18M60 43h34" />
          <circle cx="88" cy="18" r="4.2" />
        </g>
      );
    case 'coast':
      return (
        <g>
          <path className={styles.horizon} d="M34 48h66" />
          <path d="M36 53q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M39 58q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M43 63q 5 -2 10 0 t 10 0 t 10 0 t 10 0 t 10 0 t 10 0" />
          <path d="M42 47V35l9 12h-9Z" />
          <path d="M39 49q 7 4 14 0" />
          <circle cx="88" cy="17" r="4.2" />
          <path className={styles.rays} d="M88 10.5v2M88 21.5v2M81.5 17h2M92.5 17h2" />
        </g>
      );
    case 'eaves':
      return (
        <g>
          <path d="M34 44q 6 -1 9 -5c 7 -6 18 -8 28 -4c 4 2 7 4 12 4c 4 0 7 -1 10 -3" />
          <path d="M35 47q 9 -2 17 -7" />
          <path d="M42 48v13M52 48v13M76 48v13M88 48v13" />
          <path d="M58 39h18v11H58Z" />
          <path d="M58 43h18M67 39v11" />
          <path className={styles.horizon} d="M34 61h66" />
        </g>
      );
    case 'skyline':
      return (
        <g>
          <path d="M34 61V46h7v15M41 61V34h9v27M50 61V40h7v21M57 61V27h11v34M68 61V37h8v24M76 61V22h10v39M86 61V41h7v20M93 61V31h5v30" />
          <path className={styles.windows} d="M43.5 39h4M43.5 44h4M60 32h5M60 37h5M78 27h6M78 33h6M88 46h3M88 51h3" />
          <path className={styles.horizon} d="M34 61h66" />
        </g>
      );
    case 'dunes':
      return (
        <g>
          <path d="M34 56c 10 -8 22 -9 34 -2c 12 7 24 6 34 -3" />
          <path d="M36 62c 9 -6 19 -7 29 -1c 10 6 21 6 32 0" />
          <path className={styles.secondary} d="M40 48c 7 -5 14 -6 21 -3" />
          <circle cx="85" cy="18" r="5" />
          <circle className={styles.dot} cx="44" cy="50" r=".7" />
          <circle className={styles.dot} cx="47" cy="49.4" r=".7" />
          <circle className={styles.dot} cx="50" cy="50" r=".7" />
        </g>
      );
    case 'snow':
      return (
        <g>
          <path d="M34 59 L47 31 l7 12 l9 -20 l12 28 l8 -13 l9 21" />
          <path className={styles.secondary} d="M47 31l-3 8l3-1l2 2l2-5M63 23l-2 8l3-1l2 2l2-5" />
          <path className={styles.horizon} d="M36 61h64" />
          <circle className={styles.dot} cx="42" cy="20" r=".8" />
          <circle className={styles.dot} cx="52" cy="16" r=".6" />
          <circle className={styles.dot} cx="44" cy="30" r=".6" />
          <circle className={styles.dot} cx="89" cy="25" r=".7" />
        </g>
      );
    case 'garden':
      return (
        <g>
          <circle cx="38" cy="38" r="8.5" />
          <path d="M31.5 38h13M38 31.5v13" />
          <path d="M45 30v-6M45 26c 3 -2.5 6 -1.5 7 2M45 23c -3 -2 -5.5 0 -5.5 3" />
          <path className={styles.horizon} d="M27 52h20" />
          <path className={styles.mist} d="M29 56q 4 -2 8 0t8 0" />
        </g>
      );
    case 'bamboo':
      return (
        <g>
          <path d="M40 63c 1 -14 1 -26 3 -40M51 63c 0 -12 0 -23 -1 -36M88 63c 1 -16 0 -29 3 -43" />
          <path className={styles.windows} d="M41 51h3M42 43h3M43 35h2M51 49h2M51 41h2M89 51h3M89 43h3M89 35h3" />
          <path d="M43 29c 5 -4 9 -3 11 1M35 25c 4 -3 8 -2 10 2M89 27c 4 -3 8 -2 10 2M81 32c 4 -3 7 -2 9 1" />
          <path className={styles.horizon} d="M36 63h60" />
        </g>
      );
    default:
      return null;
  }
}

/** 字内纹理：同一母题的密集线/网格/点阵，只透过首字显影。 */
function CoverTexture({ motif }: { motif: CoverMotif }) {
  switch (motif) {
    case 'water':
    case 'coast':
      return (
        <g>
          {Array.from({ length: 10 }, (_, index) => (
            <path
              key={index}
              d={`M46 ${12 + index * 5}q 5 -2.5 10 0t 10 0t 10 0t 10 0t 10 0`}
            />
          ))}
        </g>
      );
    case 'mountain':
      return (
        <g>
          {[0, 1, 2, 3].map(index => (
            <path
              key={index}
              d={`M46 ${56 - index * 7}L58 ${34 - index * 5}L64 ${45 - index * 7}L73 ${18 + index * 3}L81 ${42 - index * 4}L89 ${28 - index * 3}L96 ${56 - index * 7}`}
            />
          ))}
        </g>
      );
    case 'eaves':
      return (
        <g>
          {Array.from({ length: 8 }, (_, index) => (
            <path key={`h${index}`} d={`M50 ${12 + index * 6}h46`} />
          ))}
          {Array.from({ length: 8 }, (_, index) => (
            <path key={`v${index}`} d={`M${52 + index * 6} 12v48`} />
          ))}
        </g>
      );
    case 'skyline':
      return (
        <g>
          {Array.from({ length: 8 }, (_, index) => (
            <path key={`h${index}`} d={`M50 ${14 + index * 6}h46`} />
          ))}
          {Array.from({ length: 10 }, (_, index) => (
            <path key={`v${index}`} d={`M${50 + index * 5} 12v48`} />
          ))}
        </g>
      );
    case 'dunes':
      return (
        <g>
          {Array.from({ length: 7 }, (_, index) => (
            <path key={index} d={`M44 ${58 - index * 6}q 22 -18 52 -8`} />
          ))}
        </g>
      );
    case 'snow':
      return (
        <g>
          {Array.from({ length: 6 }, (_, row) =>
            Array.from({ length: 9 }, (_, column) => (
              <circle
                key={`${row}-${column}`}
                className={styles.textureDot}
                cx={47 + column * 6 + (row % 2) * 3}
                cy={12 + row * 8}
                r=".7"
              />
            )),
          )}
        </g>
      );
    case 'garden':
      return (
        <g>
          {Array.from({ length: 6 }, (_, index) => (
            <path key={`v${index}`} d={`M${50 + index * 8} 12v48`} />
          ))}
          {Array.from({ length: 6 }, (_, index) => (
            <path key={`h${index}`} d={`M46 ${14 + index * 8}h54`} />
          ))}
          <path d="M50 24c 6 -5 12 -4 15 2M56 42c 5 -4 10 -3 13 1" />
        </g>
      );
    case 'bamboo':
      return (
        <g>
          {Array.from({ length: 5 }, (_, index) => (
            <path key={`s${index}`} d={`M${50 + index * 10} 12v48`} />
          ))}
          {Array.from({ length: 5 }, (_, row) => (
            <path
              key={`n${row}`}
              d={`M${50 + row * 10} ${20 + row * 9}h4M${56 + row * 10} ${25 + row * 8}h4`}
            />
          ))}
          <path d="M48 22c 6 -4 10 -3 13 1M55 32c 6 -4 11 -3 14 1M48 46c 5 -3 9 -2 12 1M65 42c 5 -3 10 -2 13 1" />
        </g>
      );
    default:
      return null;
  }
}

/**
 * 地名印章封面：把地点首字做成大号字徽，字内刻进当地风景，
 * 字后是低透明度的地方线稿，外加一圈虚线印环。不依赖任何网络图片。
 * 色板、首字与风景母题都由城市名确定性生成。
 */
export function TripCover({ city, dateRange, days, size = 'card', kicker, className }: TripCoverProps) {
  const tone = coverTone(city);
  const motif = coverMotif(city);
  const glyph = coverGlyph(city);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const maskId = 'cover-mask-' + uid;
  const sceneMaskId = 'cover-scene-' + uid;
  const sceneFadeId = 'cover-scene-fade-' + uid;
  const meta = [typeof days === 'number' ? days + ' 天' : '', dateRange ?? ''].filter(Boolean).join(' · ');
  const glyphProps = {
    x: 74,
    y: 36.5,
    textAnchor: 'middle',
    dominantBaseline: 'central',
    transform: 'rotate(-4 74 36.5)',
  } as const;

  return (
    <div className={cx(styles.cover, styles[size], className)} data-tone={tone}>
      <svg
        className={styles.art}
        viewBox="0 0 100 75"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id={sceneFadeId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fff" />
            <stop offset="0.32" stopColor="#fff" />
            <stop offset="0.58" stopColor="#000" />
          </linearGradient>
          <mask id={sceneMaskId} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="75">
            <rect x="0" y="0" width="100" height="75" fill={`url(#${sceneFadeId})`} />
          </mask>
          <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="75">
            <text {...glyphProps} className={styles.glyph} fill="#fff">
              {glyph}
            </text>
          </mask>
        </defs>

        <g className={styles.scene} mask={`url(#${sceneMaskId})`}>
          <CoverScene motif={motif} />
        </g>

        <g className={styles.seal}>
          <circle className={styles.sealRing} cx="74" cy="36.5" r="25" />
          <circle className={styles.sealDot} cx="74" cy="13" r=".9" />
        </g>

        <text {...glyphProps} x={75.8} y={38.3} className={cx(styles.glyph, styles.glyphGhost)}>
          {glyph}
        </text>

        <g mask={`url(#${maskId})`}>
          <rect className={styles.glyphFill} x="0" y="0" width="100" height="75" />
          <g className={styles.texture}>
            <CoverTexture motif={motif} />
          </g>
        </g>

        <text {...glyphProps} className={cx(styles.glyph, styles.glyphOutline)}>
          {glyph}
        </text>
      </svg>

      <div className={styles.head}>
        <span className={styles.kicker}>{kicker ?? '行迹 · TRIP'}</span>
      </div>
      <div className={styles.body}>
        <h3 className={styles.city}>{city}</h3>
        {meta && size !== 'thumb' ? <span className={styles.meta}>{meta}</span> : null}
      </div>
    </div>
  );
}
