import { useHashRoute } from '../../app/routing/useHashRoute';
import { BackIcon } from '../../components/icons';
import { Kicker } from '../../components/ui/Kicker';
import { useOperatorInfo } from '../../lib/legal';
import { backTarget, originSuffix } from '../../lib/legalNav';
import styles from './auth.module.css';

export function TermsPage() {
  const { navigate } = useHashRoute();
  const operator = useOperatorInfo();
  const back = backTarget();
  const privacyHref = '#/privacy' + originSuffix();

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.topbar}>
          <button type="button" className={styles.back} onClick={() => navigate(back)}>
            <BackIcon size={18} />
            返回
          </button>
          <Kicker className={styles.kicker}>TERMS</Kicker>
        </div>

        <header className={styles.header}>
          <h1 className={styles.title}>服务条款</h1>
          <p className={styles.lede}>{operator.name ? `行迹 Trip · ${operator.name}` : '行迹 Trip · 演示版'}</p>
          <p className={styles.meta}>最近更新：2026 年 11 月</p>
        </header>

        <article className={styles.legal}>
          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>1. 关于行迹 Trip</h2>
            <p className={styles.legalBody}>
              行迹 Trip 是一个 AI 旅游行程规划 Web 应用。你可以输入目的地、日期、同行人数、兴趣与预算，由模型生成每日行程，并在地图上查看地点。服务可能随时调整、暂停或下线部分功能。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>2. 账号</h2>
            <p className={styles.legalBody}>
              你可以先以游客身份试用，草稿只保存在当前浏览器。注册账号后，行程可以跨设备保存，也才能使用分享链接与协作。请妥善保管密码；发现账号被他人使用时，请尽快在「设置 → 账户设置」修改密码。
            </p>
            <p className={styles.legalBody}>
              一个邮箱只能绑定一个账号。注册后请按邮件提示验证邮箱，验证后才能使用邮箱找回密码。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>3. 你创建的行程与内容</h2>
            <p className={styles.legalBody}>
              城市、日期、兴趣、必去地点、预算与花费等内容由你填写或确认，权利仍归你。你授权我们在提供行程保存、生成、地图展示和分享功能所必需的范围内处理这些内容。请不要填写他人的隐私信息、身份证件号码或支付密码等敏感信息。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>4. AI 生成内容</h2>
            <p className={styles.legalBody}>
              行程由 DeepSeek 模型根据你的输入生成，地点与路线信息来自高德地图。AI 可能出错，营业时间、门票、交通与天气也可能变化。出发前请通过官方渠道再次确认，不要把生成结果当作安全、医疗、签证或法律建议。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>5. 使用规范</h2>
            <ul className={styles.legalList}>
              <li>不要用自动化脚本批量请求、抓取或干扰服务。</li>
              <li>不要上传违法、侵权、骚扰或危害他人的内容。</li>
              <li>不要尝试绕过登录、访问他人账号或分享链接之外的数据。</li>
              <li>不要将服务用于虚假预订、欺诈或其他违法用途。</li>
            </ul>
            <p className={styles.legalBody}>
              违反上述规范时，我们可能限制或停止相关账号的使用。当前没有付费功能，也不提供任何形式的旅行保险或履约担保。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>6. 服务变更与终止</h2>
            <p className={styles.legalBody}>
              我们可以因维护、安全或产品调整而修改或停止服务。你可以随时在「设置 → 账户设置 → 注销账号」永久删除账号。删除后，账号下的行程、协作、分享链接、预算与花费将无法恢复。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>7. 免责声明</h2>
            <p className={styles.legalBody}>
              本服务按现状提供。因网络、第三方地图或模型服务不可用导致的生成失败、信息延迟或行程偏差，我们会尽力修复，但不对由此产生的间接损失承担责任。法律允许的最大范围内，本条适用。
            </p>
          </section>

          <section className={styles.legalSection}>
            <h2 className={styles.legalTitle}>8. 条款更新</h2>
            <p className={styles.legalBody}>
              条款更新后，已登录用户会在「我的」看到提示。继续使用前，你可以查看并同意最新版本；不同意时，可以选择不再使用并注销账号。隐私相关事项见
              <a className={styles.legalLink} href={privacyHref}>隐私政策</a>。
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
            <p>行迹 Trip 演示版 · 条款与隐私说明会随功能调整更新。</p>
          )}
          <a className={styles.legalLink} href={privacyHref}>查看隐私政策</a>
        </footer>
      </div>
    </main>
  );
}
