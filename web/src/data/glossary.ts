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
  }
}
