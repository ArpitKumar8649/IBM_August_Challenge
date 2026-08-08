export interface GlossaryTerm {
  id: string
  term: string
  shortDef: string
  longDef: string
  knowledgeTopic?: string
}

export const GLOSSARY: Record<string, GlossaryTerm> = {
  tca: {
    id: 'tca',
    term: 'Time of Closest Approach (TCA)',
    shortDef: 'The exact moment two objects pass closest to each other.',
    longDef: 'TCA is the timestamp of minimum separation between two orbiting bodies. OrbitWarden refines this to 0.01-second precision to accurately compute the miss distance and collision probability.',
  },
  miss: {
    id: 'miss',
    term: 'Miss Distance',
    shortDef: 'The distance between the centers of two objects at TCA.',
    longDef: 'The predicted distance between two satellites at their closest point. In low Earth orbit, miss distances under 1 kilometer are typically flagged for review, while distances under 100 meters often trigger an avoidance maneuver.',
  },
  vrel: {
    id: 'vrel',
    term: 'Relative Velocity',
    shortDef: 'How fast the two objects are moving past each other.',
    longDef: 'The speed at which the objects pass one another at TCA. In low Earth orbit, this is typically 10 to 15 kilometers per second (over 33,000 mph). High relative velocity means less time for perturbations to change the outcome, making the encounter more predictable.',
  },
  pc: {
    id: 'pc',
    term: 'Collision Probability (Pc)',
    shortDef: 'The mathematical likelihood that the two objects will hit.',
    longDef: 'Pc combines the miss distance, the size of the objects, and the uncertainty in their predicted positions. A Pc of 1e-4 (1 in 10,000) is a common threshold for action. OrbitWarden computes this using the Alfriend-Foster method on the B-plane.',
    knowledgeTopic: 'collision-probability'
  },
  rsw: {
    id: 'rsw',
    term: 'RSW Geometry',
    shortDef: 'The miss distance broken down by direction relative to your satellite.',
    longDef: 'RSW stands for Radial (up/down), S or In-track (forward/backward), and W or Cross-track (left/right). Knowing whether a miss is mostly in-track or cross-track tells the operator which way to burn to avoid it.',
    knowledgeTopic: 'geometry'
  },
  bplane: {
    id: 'bplane',
    term: 'B-plane',
    shortDef: 'A 2D plane used to visualize the encounter and compute risk.',
    longDef: 'The B-plane (or encounter plane) is perpendicular to the relative velocity of the two objects. Imagine standing on your satellite and watching the other object approach: the B-plane is the "screen" it punches through. It makes the 3D miss geometry easy to see.',
    knowledgeTopic: 'collision-probability'
  },
  kp: {
    id: 'kp',
    term: 'Kp Index',
    shortDef: 'A measure of geomagnetic storm activity (0 to 9).',
    longDef: 'The Kp index measures disturbances in the Earth\'s magnetic field caused by the solar wind. A Kp of 5 or higher is a geomagnetic storm. Storms heat the upper atmosphere, increasing drag on satellites and making predictions uncertain.',
    knowledgeTopic: 'atmosphere'
  },
  dv: {
    id: 'dv',
    term: 'Delta-v (Δv)',
    shortDef: 'The change in velocity required for a maneuver.',
    longDef: 'Delta-v is the measure of impulse needed to change a satellite\'s orbit. It determines how much propellant is consumed. OrbitWarden calculates "fuel-optimal" maneuvers that achieve a safe miss distance using the minimum possible Δv.',
    knowledgeTopic: 'maneuver-planning'
  },
  risk_score: {
    id: 'risk_score',
    term: 'Risk Score',
    shortDef: 'A 0-100 ranking of how much a conjunction deserves attention.',
    longDef: 'OrbitWarden\'s composite score combines how close the miss is, how fast the objects are closing, the encounter geometry, and whether the other object can maneuver. It deliberately does NOT rely on collision probability alone, because that number depends on uncertain assumptions — geometry and timing are more trustworthy. 60+ is red (act), 40-60 is amber (watch closely), below 40 is routine monitoring.',
    knowledgeTopic: 'conjunction-assessment'
  },
  storm_flag: {
    id: 'storm_flag',
    term: 'Storm Flag',
    shortDef: 'Warning that space weather is inflating prediction uncertainty.',
    longDef: 'When geomagnetic activity (Kp index) is high, the atmosphere expands, increasing drag. This makes orbit predictions degrade faster. A storm flag means the reported miss distance is uncertain and must be re-screened closer to TCA.',
    knowledgeTopic: 'atmosphere'
  },
  cdm: {
    id: 'cdm',
    term: 'Conjunction Data Message (CDM)',
    shortDef: 'The standard alert message for a close approach.',
    longDef: 'A standard format (CCSDS 508.0-B-1) used by space agencies and tracking networks to share information about an impending close approach, including miss distance, TCA, and collision probability.',
    knowledgeTopic: 'standards'
  },
  globe_3d: {
    id: 'globe_3d',
    term: '3D Conjunction Globe',
    shortDef: 'A 3D view of the encounter in space, drawn straight from the engine.',
    longDef: 'The 3D View tab renders the conjunction the way an operator sees it: both orbits animating on a scrubbable timeline, the miss line and relative-velocity arrow at TCA, the covariance ellipsoid, and the maneuver pre/post-burn track. The scene is an engine-composed CZML document — the browser only draws what the physics plane computed, never re-deriving orbit geometry — so the globe, the B-plane figure, and the event card always agree. CesiumJS, the same engine that powers NASA Eyes, drives the rendering.',
    knowledgeTopic: 'conjunction-assessment'
  },
  covariance_ellipsoid: {
    id: 'covariance_ellipsoid',
    term: 'Covariance Ellipsoid',
    shortDef: 'The 3D shape of where the secondary might actually be at TCA.',
    longDef: 'Orbit predictions are never exact — tracking uncertainty grows between observations. The covariance ellipsoid is the 3D version of the B-plane\'s σ contours: the region that most likely contains the secondary at TCA, drawn around it at 1σ (scaled ×10 so it is visible against the orbit scale). A miss that passes through the ellipsoid is a different risk than one far outside it — this is exactly why the B-plane reports the miss in \"sigmas out\".',
    knowledgeTopic: 'collision-probability'
  },
  maneuver_track: {
    id: 'maneuver_track',
    term: 'Maneuver Track',
    shortDef: 'The pre-burn and post-burn orbits diverging at the burn epoch.',
    longDef: 'Selecting a burn option adds the maneuver track: the primary\'s orbit before the burn and its new orbit after, pulled apart at the burn epoch so you can watch the avoidance burn \"pull\" the two objects apart. The post-burn path is numerically propagated and re-screened by the engine — the post-burn miss distance on the maneuver cards is the geometry this scene draws.',
    knowledgeTopic: 'maneuver-planning'
  }
}
