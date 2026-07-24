import { Link } from 'react-router-dom'
import Reveal from '../components/Reveal'
import CountUp from '../components/CountUp'
import OrbitScene from '../components/OrbitScene'
import { CDM_STATS, SAMPLE_EVENTS } from '../data/sample'
import '../styles/landing.css'

const TICKER_ITEMS = SAMPLE_EVENTS.slice(0, 6)

export default function Landing() {
  return (
    <div className="landing">
      {/* ---------- nav ---------- */}
      <nav className="nav">
        <div className="nav-inner">
          <Link to="/" className="brand">
            <span className="script">OrbitWarden</span>
            <span className="tag">collision-avoidance</span>
          </Link>
          <div className="nav-links">
            <a href="#problem">The Threat</a>
            <a href="#how">How it works</a>
            <a href="#validation">Validation</a>
            <a href="#analyst">The Analyst</a>
            <Link to="/dashboard" className="btn btn-primary">Mission Control</Link>
          </div>
        </div>
      </nav>

      {/* ---------- hero ---------- */}
      <header className="hero">
        <div className="wrap hero-grid">
          <div className="hero-copy">
            <Reveal>
              <span className="eyebrow">IBM AI Builders Challenge · Space Exploration</span>
            </Reveal>
            <Reveal delay={1}>
              <h1 className="hero-title">
                <span className="script hero-script">OrbitWarden</span>
                <span className="hero-sub">
                  The collision-avoidance desk for satellites that can't afford one.
                </span>
              </h1>
            </Reveal>
            <Reveal delay={2}>
              <p className="hero-lede">
                OrbitWarden screens your spacecraft against every tracked object in orbit,
                explains which conjunctions actually matter, and drafts propellant-aware
                avoidance maneuvers — powered by IBM Granite, with every number provably
                computed by physics, never invented by a model.
              </p>
            </Reveal>
            <Reveal delay={3}>
              <div className="hero-actions">
                <Link to="/dashboard" className="btn btn-primary">
                  Open Mission Control <span aria-hidden>→</span>
                </Link>
                <a href="#validation" className="btn btn-ghost">See the validation</a>
              </div>
            </Reveal>
            <Reveal delay={4}>
              <div className="hero-stats">
                <div><strong className="mono">18,753</strong><span>objects screened</span></div>
                <div><strong className="mono">9/10</strong><span>SOCRATES events matched</span></div>
                <div><strong className="mono">&lt;1 mm</strong><span>SGP4 reference accuracy</span></div>
              </div>
            </Reveal>
          </div>
          <div className="hero-visual">
            <Reveal delay={2}>
              <OrbitScene />
            </Reveal>
          </div>
        </div>
      </header>

      {/* ---------- threat ticker ---------- */}
      <div className="ticker" aria-hidden="true">
        <div className="ticker-track">
          {[...TICKER_ITEMS, ...TICKER_ITEMS].map((e, i) => (
            <span key={i} className="ticker-item mono">
              <b className={e.risk_score > 60 ? 't-danger' : 't-warn'}>▲</b>
              {e.secondary_name} · miss {e.miss_km.toFixed(2)} km · {e.vrel_kms.toFixed(1)} km/s
              · TCA {new Date(e.tca).toISOString().slice(5, 16).replace('T', ' ')}Z
            </span>
          ))}
        </div>
      </div>

      {/* ---------- problem ---------- */}
      <section id="problem">
        <div className="wrap">
          <Reveal><span className="eyebrow">The problem</span></Reveal>
          <Reveal delay={1}>
            <h2 className="section-title">
              Low Earth Orbit is crowded — <span className="script accent-script">and getting worse.</span>
            </h2>
          </Reveal>
          <div className="problem-grid">
            <Reveal delay={1} className="problem-card panel panel-lift">
              <div className="problem-num mono"><CountUp value={35000} suffix="+" /></div>
              <h3>tracked objects</h3>
              <p>and climbing with mega-constellations. Starlink alone executes thousands of collision-avoidance burns a year.</p>
            </Reveal>
            <Reveal delay={2} className="problem-card panel panel-lift">
              <div className="problem-num mono"><CountUp value={2} /></div>
              <h3>people on the team</h3>
              <p>University CubeSat crews get cryptic miss-distance lists and are expected to decide alone — no analysts, no tooling, no time.</p>
            </Reveal>
            <Reveal delay={3} className="problem-card panel panel-lift">
              <div className="problem-num mono">1<span style={{fontSize:'0.5em'}}> of 2</span></div>
              <h3>choices, both bad</h3>
              <p>Over-maneuver and you burn scarce propellant, shortening the mission. Under-react and you risk the satellite.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- how it works ---------- */}
      <section id="how" className="alt">
        <div className="wrap">
          <Reveal><span className="eyebrow">How it works</span></Reveal>
          <Reveal delay={1}>
            <h2 className="section-title">
              <span className="script accent-script">Physics computes.</span> The AI judges.
            </h2>
          </Reveal>
          <Reveal delay={2}>
            <p className="section-lede">
              A deterministic astrodynamics engine produces every number. The Granite agent
              does the judgment — triage, maneuver selection, explanation. A validation layer
              guarantees no invented figure ever reaches the operator.
            </p>
          </Reveal>
          <div className="flow">
            {[
              { n: '01', t: 'Screen', d: 'Propagate your satellite and the full catalog with SGP4; find every close approach over the next 7 days.' },
              { n: '02', t: 'Triage', d: 'Rank conjunctions by geometry, velocity, and who can maneuver — with plain-English rationale.' },
              { n: '03', t: 'Plan', d: 'Shoot-and-score maneuver search returns propellant-costed options that meet your constraints.' },
              { n: '04', t: 'Validate', d: 'Every number is checked against the engine before it is shown. The card is server-composed.' },
            ].map((s, i) => (
              <Reveal key={s.n} delay={(i % 4) as 0 | 1 | 2 | 3} className="flow-step panel panel-lift">
                <div className="flow-num mono">{s.n}</div>
                <h3>{s.t}</h3>
                <p>{s.d}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- validation ---------- */}
      <section id="validation">
        <div className="wrap">
          <Reveal><span className="eyebrow">Validated against ground truth</span></Reveal>
          <Reveal delay={1}>
            <h2 className="section-title">
              We replayed <span className="script accent-script">real conjunctions</span> the Space
              Surveillance Network flagged.
            </h2>
          </Reveal>
          <Reveal delay={2}>
            <p className="section-lede">
              Using era-correct TLEs, OrbitWarden reproduced the CDMs' reported geometry —
              honest about where fast analytic screening agrees with precision propagation,
              and where it doesn't.
            </p>
          </Reveal>
          <div className="val-grid">
            <Reveal delay={1} className="val-card panel panel-lift">
              <div className="val-num mono">
                <CountUp value={CDM_STATS.detected} />/{CDM_STATS.total}
              </div>
              <div className="val-label">conjunctions detected</div>
              <p>The 4 misses were missing ephemerides, not engine failures.</p>
            </Reveal>
            <Reveal delay={2} className="val-card panel panel-lift">
              <div className="val-num mono"><CountUp value={CDM_STATS.median_miss_ratio} decimals={2} suffix="×" /></div>
              <div className="val-label">median miss-distance ratio</div>
              <p>km-scale conjunctions agree to within ~20% of precision propagation.</p>
            </Reveal>
            <Reveal delay={3} className="val-card panel panel-lift">
              <div className="val-num mono"><CountUp value={CDM_STATS.median_tca_err_s} decimals={2} suffix=" s" /></div>
              <div className="val-label">median TCA error</div>
              <p>Time of closest approach, essentially exact.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- analyst showcase ---------- */}
      <section id="analyst" className="alt">
        <div className="wrap analyst-grid">
          <div>
            <Reveal><span className="eyebrow">The judgment layer</span></Reveal>
            <Reveal delay={1}>
              <h2 className="section-title">
                An analyst that <span className="script accent-script">never invents a number.</span>
              </h2>
            </Reveal>
            <Reveal delay={2}>
              <p className="section-lede">
                Ask it in plain language. It calls its tools, reads the engine, and explains
                the tradeoff — then hands you a maneuver card for approval. You stay in the loop;
                it never executes.
              </p>
            </Reveal>
            <Reveal delay={3}>
              <ul className="analyst-points">
                <li><span className="mono pt-num">→</span> Strict tool-calling: the model's only way to touch numbers</li>
                <li><span className="mono pt-num">→</span> Server-composed cards: figures filled by the engine, not the model</li>
                <li><span className="mono pt-num">→</span> Output validation: invented numbers are flagged before you see them</li>
              </ul>
            </Reveal>
          </div>
          <Reveal delay={2}>
            <div className="chat-mock panel">
              <div className="chat-head">
                <span className="chat-dot" /> OrbitWarden Analyst
                <span className="chip good" style={{ marginLeft: 'auto' }}>audit passed</span>
              </div>
              <div className="chat-body">
                <div className="msg user">What's my most urgent conjunction?</div>
                <div className="msg tool mono">⚙ list_conjunctions · get_event_details</div>
                <div className="msg bot">
                  Your top threat is <b>2023-091AL</b> — a 3.04 km miss on Jul 26 at 01:18 UTC,
                  closing at 9.89 km/s on a radial approach. It can't maneuver, so you'd be the
                  one to move.
                </div>
                <div className="msg user">Plan a burn — I have 100 g margin, want a 90 km miss.</div>
                <div className="msg tool mono">⚙ search_maneuvers · submit_maneuver_card</div>
                <div className="msg bot">
                  A 5 m/s in-track burn 60 min before TCA raises the miss to <b>410.6 km</b> for
                  33.8 g — well within your margin. Card ready for your approval.
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------- stack ---------- */}
      <section id="stack">
        <div className="wrap">
          <Reveal><span className="eyebrow">Built on</span></Reveal>
          <Reveal delay={1}>
            <div className="stack-row">
              {['IBM Granite', 'watsonx.ai', 'IBM Bob', 'SGP4 / Astrodynamics', 'FastAPI', 'React', 'Code Engine'].map((t) => (
                <span key={t} className="chip">{t}</span>
              ))}
            </div>
          </Reveal>
          <Reveal delay={2}>
            <div className="cta-band panel">
              <h2 className="script cta-script">Take the controls.</h2>
              <p>Explore a live screening of the International Space Station.</p>
              <Link to="/dashboard" className="btn btn-primary">Open Mission Control →</Link>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------- footer ---------- */}
      <footer className="footer">
        <div className="wrap footer-grid">
          <div>
            <div className="brand"><span className="script">OrbitWarden</span></div>
            <p className="footer-note">
              Built for the IBM AI Builders Challenge — August 2026 · Advance Space Exploration with AI.
            </p>
          </div>
          <div className="footer-col">
            <span className="footer-h mono">Project</span>
            <a href="https://github.com/ArpitKumar8649/IBM_August_Challenge">GitHub</a>
            <a href="#validation">Validation report</a>
            <Link to="/dashboard">Mission Control</Link>
          </div>
          <div className="footer-col">
            <span className="footer-h mono">Principle</span>
            <p className="footer-note">Physics computes. The AI judges. The human decides.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
