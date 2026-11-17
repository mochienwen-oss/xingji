import { useHashRoute } from '../../app/routing/useHashRoute';
import { BackIcon } from '../../components/icons';
import { Kicker } from '../../components/ui/Kicker';
import { useOperatorInfo } from '../../lib/legal';
import { backTarget, originSuffix } from '../../lib/legalNav';
import styles from './auth.module.css';

export function PrivacyPage() {
  const { navigate } = useHashRoute();
  const operator = useOperatorInfo();
  const back = backTarget();
  const termsHref = '#/terms' + originSuffix();

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={() => navigate(back)}>
            <BackIcon size={18} />
            返回
          </button>
          <Kicker className={styles.kicker}>PRIVACY</Kicker>
        </div>

        <header className={styles.header}>
          <h1 className={styles.title}>隐私政策</h1>
          <p className={styles.lede}>{operator.name ? `行迹 Trip · ${operator.name}` : '行迹 Trip · 演示版'}</p>
          <p className={styles.meta}>最近更新：2026 年 11 月</p>
        </header>

        <article className={styles.legal}>
          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>1. 我们收集什么</h2>
            <ul className={styles.legalList}>
              <li>账号信息：用户名、邮箱、密码的哈希值，以及邮箱验证与条款接受状态。</li>
              <li>行程输入：城市、日期、人数、兴趣、节奏、预算、必去地点与交通偏好。</li>
              <li>行程内容：生成的每日安排、地点、预算与花费记录、分享链接。</li>
              <li>本机草稿：游客草稿存在 sessionStorage，登录用户的草稿存在 localStorage。</li>
            </ul>
            <p className={styles.legalBody}>我们不要求真实姓名、手机号或身份证件信息，也不会收集支付卡号。</p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>2. 如何使用</h2>
            <ul className={styles.legalList}>
              <li>生成与保存行程，展示地图和地点详情。</li>
              <li>把行程输入与提示词发送给 DeepSeek 模型服务，用于生成每日安排。</li>
              <li>向高德地图查询城市、地点与坐标，用于地图与路线展示。</li>
              <li>向你的邮箱发送验证、修改邮箱和重置密码邮件。</li>
              <li>排查故障、防止滥用，并维护登录状态。</li>
            </ul>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>3. 邮箱的用途</h2>
            <p className={styles.legalBody}>
              邮箱只用于账号识别、邮箱验证、找回密码和必要的安全通知，不用于广告投放，也不会出售给第三方。修改邮箱时，新地址会先进入待验证状态；验证完成前，旧邮箱仍然有效。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>4. 第三方处理</h2>
            <p className={styles.legalBody}>
              行迹 Trip 会把完成功能所必需的信息交给以下第三方处理：高德地图用于地点检索与地图展示，可能收到城市名、地点名与坐标；DeepSeek 模型服务用于生成行程，可能收到你的目的地、日期、兴趣与必去地点等提示词。第三方会按其自身规则处理数据，请同时阅读它们的隐私说明。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>5. 存储与安全</h2>
            <p className={styles.legalBody}>
              账号与行程保存在服务端数据库中，登录状态通过会话 Cookie 维持。浏览器本地只保存草稿、行程列表缓存、动效偏好等便于使用的数据。我们采取合理的技术措施保护数据，但互联网服务无法承诺绝对安全。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>6. 你的选择与删除</h2>
            <p className={styles.legalBody}>
              你可以随时修改邮箱、修改密码，或在「设置 → 账户设置 → 注销账号」永久删除账号。注销会删除账号、账号下的行程、协作与分享链接、预算与花费记录，并清理这台浏览器里的行迹本地缓存；删除后无法恢复。游客可以直接关闭页面，或用浏览器的站点数据清理功能删除本地草稿。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>7. 保留期限</h2>
            <p className={styles.legalBody}>
              账号存续期间，我们保留账号与行程数据。注销后，相关数据会从生产数据库删除；备份中的残留会在备份轮换后消失。为安全与排障产生的必要日志会在短期保留后删除或匿名化。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>8. 未成年人</h2>
            <p className={styles.legalBody}>
              本服务不面向未成年人单独提供服务。若你未满 16 周岁，请在监护人同意和指导下使用，避免填写自己或他人的敏感信息。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>9. 政策更新</h2>
            <p className={styles.legalBody}>
              功能或第三方服务变化时，我们会更新本政策并调整上方日期。涉及账号处理的重大变化，会在应用内提示。继续使用前，你可以查看
              <a className={styles.legalLink} href={termsHref}>服务条款</a>。
            </p>
          </section>
        </article>

        <footer className={styles.legalFoot}>
          {operator.name ? (
            <p>
              运营主体：{operator.name}
              {operator.contact_email ? ` · 联系：${operator.contact_email}` : ''}
              {operator.jurisdiction ? ` · 管辖地：${operator.jurisdiction}` : ''}
              {operator.icp_number ? ` · 备案：${operator.icp_number}` : ''}
            </p>
          ) : (
            <p>行迹 Trip 演示版 · 不使用真实公司主体或联系方式表述。</p>
          )}
          <a className={styles.legalLink} href={termsHref}>查看服务条款</a>
        </footer>
      </div>
    </main>
  );
}
