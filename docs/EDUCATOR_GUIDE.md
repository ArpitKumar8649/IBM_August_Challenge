# OrbitWarden Educator Guide

**Welcome to OrbitWarden!** This tool wasn’t just built for satellite operators—it’s designed to make the invisible world of orbital mechanics visible and accessible to students. 

This guide will help you use OrbitWarden in the classroom to teach concepts in physics, data literacy, and space sustainability.

---

## 1. Core Concepts to Explore

OrbitWarden turns abstract numbers into visual, physical realities. Here are the main concepts your students can explore:

### A. The Scale of Space (and the Speed)
- **Relative Velocity:** Have students look at the "rel. velocity" metric. It’s typically around **10-15 km/s** (over 33,000 mph). Ask them to calculate how long it takes to cross their city at that speed.
- **Miss Distance:** A miss of 1 kilometer might sound far on Earth, but at 15 km/s, that’s less than a tenth of a second of travel time.

### B. Uncertainty and Probability (The B-plane)
- **The B-plane Diagram:** This is the most important teaching tool in the app. It shows that we don't know *exactly* where a satellite will be. 
- **The Covariance Ellipse:** Explain that the rings (1σ, 2σ, 3σ) represent confidence intervals. It’s a real-world application of statistics. A high collision probability (Pc) happens when the "hard body" (the red circle) overlaps significantly with the likely positions of the objects.

### C. The Rocket Equation & Fuel (Delta-v)
- **Avoidance Maneuvers:** Look at the maneuver options. A typical burn requires a **Delta-v (Δv)** of maybe 0.1 to 1.0 meters per second. 
- **Propellant Cost:** Show them the propellant mass. A satellite has a strict fuel budget. Using fuel to dodge debris shortens the satellite's useful life. Ask: *Why not just do a massive burn and get far away?* (Answer: You’d run out of fuel and the mission would end.)

### D. Space Weather & Drag
- **The Storm Flag (⚠):** Solar flares and coronal mass ejections (CMEs) heat the Earth's upper atmosphere, causing it to expand.
- **Atmospheric Drag:** This expansion acts like a brake on satellites in Low Earth Orbit (LEO), changing their trajectory. When space weather is bad (high Kp index), our predictions of where the satellite will be tomorrow become highly uncertain.

---

## 2. Suggested Classroom Activities

### Activity 1: The "Go / No-Go" Decision
**Objective:** Understand risk assessment and trade-offs.
1. Have students select 3 different conjunctions from the Mission Control board.
2. For each, ask them to record the Miss Distance, Collision Probability, and required Propellant to avoid it.
3. **The Challenge:** Tell them they have a total fuel budget of only 5 grams left for the year. Which conjunction(s) do they dodge? Why?

### Activity 2: The Kessler Syndrome Debate
**Objective:** Understand the tragedy of the commons in space.
1. Navigate to the "Discovery" tab (or look at the overall tracking numbers). Note the number of tracked objects.
2. Explain the **Kessler Syndrome**: collisions create debris, which creates more collisions, eventually making orbit unusable.
3. Discuss: *Who is responsible for cleaning up orbit? Should companies be fined if they don't de-orbit their dead satellites?*

### Activity 3: Unpacking the B-Plane
**Objective:** Visualize 3D geometry in 2D.
1. Pick a conjunction and open the B-plane plot.
2. Have students draw what they think the encounter looks like in 3D (one satellite moving forward, one cutting across).
3. Explain that the B-plane is the "window pane" the other satellite punches through from our perspective.

---

## 3. Glossary for Teachers

If a student asks what a term means, you can click the `?` icon next to it in the app for a plain-language explanation. The core terms are:

- **TCA (Time of Closest Approach):** The exact moment the two objects pass closest to each other.
- **Pc (Collision Probability):** The mathematical likelihood they will hit, factoring in our uncertainty about their exact positions.
- **RSW Geometry:** Which direction the miss is (Radial/up-down, In-track/forward-back, Cross-track/left-right).
- **Kp Index:** A measure of space weather (solar storms). 5 or higher is a storm.

---

*Physics computes. The AI judges. The human decides. And now, the student learns.*
