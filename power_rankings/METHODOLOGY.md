# PolyTrack Global Player Rating System

A comprehensive guide to how the PolyTrack power rankings work: how we score individual tracks, handle player counts, reward World Records, and balance top end speed with track variety.

---

## 1. Why We Built This System

Measuring player skill in a time attack game like **PolyTrack** presents unique challenges:

1. **Official Campaign Tracks (17 Tracks):** Ranging from ~370,000 players on Desert 2 up to nearly 4.5 million players on Summer 1 (with 5 tracks exceeding 1 million competitors). These tracks have extensive community participation, where leaderboard margins are separated by hundredths of a second.
2. **Community Tracks (61 Tracks):** A curated pool of verified player-created courses. Participation ranges from over 140,000 players on popular tracks like Sky Bound down to around 7,350 players on tracks like Flying Dreams.

### Problems with Common Leaderboard Systems:
* **Total Points Grinding:** Basic systems that add up all track points ($1\text{st} = 100\text{ pts}$) reward playtime over skill. Someone grinding top 20s on 60 less active tracks would outscore a player holding 8 World Records on the hardest official campaign tracks.
* **Elo Doesn't Fit Time Attacks:** Elo or match based ratings penalize players for doing casual or exploratory runs on new tracks.
* **The 2nd Place Cliff:** Simple $1/\text{Rank}$ formulas slash 2nd place down to 50% points. Being 0.01s behind the World Record on a track with 4.5 million players shouldn't cut your score in half.

### How The System Solves This:
1. **Top Speed (Top 6 Tracks, 70% Weight):** Evaluates how fast you are on your strongest tracks.
2. **Track Variety (Top 15 Tracks, 30% Weight):** Evaluates whether you can maintain that pace across 15 different maps without requiring you to play all 78.

---

## 2. The Rating Pipeline

```
                                  ┌─────────────────────────────────────────┐
                                  │      78 Scraped Track Leaderboards      │
                                  │ (17 Main Tracks + 61 Community Tracks)  │
                                  └────────────────────┬────────────────────┘
                                                       │
                                                       ▼
                                  ┌─────────────────────────────────────────┐
                                  │ Step 1: Track Multiplier (ω_k)          │
                                  │    ω_k = 1.0 + 0.18 · log10(N_k / 100k) │
                                  └────────────────────┬────────────────────┘
                                                       │
                                                       ▼
                                  ┌─────────────────────────────────────────┐
                                  │ Step 2: Track Points & WR Bonus (S_i,k) │
                                  │ S_i,k = ω_k · 100 · R(Rank) · WR Bonus  │
                                  └────────────────────┬────────────────────┘
                                                       │
                                       ┌───────────────┴───────────────┐
                                       ▼                               ▼
                      ┌─────────────────────────────────┐   ┌─────────────────────────────────┐
                      │            Engine 1             │   │            Engine 2             │
                      │   Peak Quality Index (PQI)      │   │ Versatility & Depth Index (VDI) │
                      │     Top 6 Best Tracks (70%)     │   │    Top 15 Best Tracks (30%)     │
                      └────────────────┬────────────────┘   └────────────────┬────────────────┘
                                       │                                     │
                                       └───────────────┬─────────────────────┘
                                                       │
                                                       ▼
                                  ┌─────────────────────────────────────────┐
                                  │  Engine 3: Global Skill Index (GSI)     │
                                  │  GSI = 1000 + 200 · (0.70·Z_PQI + 0.30·Z_VDI) │
                                  └─────────────────────────────────────────┘
```

---

## Step 1: Track Difficulty Scaling ($\omega_k$)

Taking 1st place on *Summer 1* (4.5 million players) requires beating massive competition. Taking 1st place on a community track like *Flying Dreams* (7,350 players) is a great run, but the depth of competition is naturally different.

Each track $k$ receives a multiplier $\omega_k$ based on its total player count $N_k$:

$$\omega_k = \text{clamp}\left( 1.0 + 0.18 \cdot \log_{10}\left( \frac{N_k}{100,000} \right), \; 0.65, \; 1.85 \right)$$

### How the Multiplier Scales:
* **The 100,000 Player Baseline:** At $100\text{k}$ players, $\log_{10}(1) = 0$, giving a baseline multiplier of **$\omega = 1.00$**.
* **Each $10\times$ Increase in Players:** Adds **$+0.18$** to the multiplier.
* **Bounds:** Floored at **$0.65$** (so low traffic tracks don't award too many points) and capped at **$1.85$**.

### Representative Track Multipliers Across the Ecosystem:

| Track Name | Category | Total Players ($N_k$) | Multiplier ($\omega_k$) | WR Max Points |
|:---|:---|:---:|:---:|:---:|
| **Summer 1** | Main Campaign | 4,496,080 | **$1.30\times$** | **162.1 pts** |
| **Summer 3** | Main Campaign | 1,980,065 | **$1.23\times$** | **154.2 pts** |
| **Desert 2** | Main Campaign | 370,871 | **$1.10\times$** | **137.9 pts** |
| **Sky Bound** | Community Track | 141,965 | **$1.03\times$** | **128.4 pts** |
| **Lenore** | Community Track | 57,834 | **$0.96\times$** | **119.7 pts** |
| **Flying Dreams** | Community Track | 7,353 | **$0.80\times$** | **99.5 pts** |

---

## Step 2: Track Scoring & The World Record Bonus ($S_{i,k}$)

Points for a given track placement are calculated using a **logarithmic decay curve** plus a **$1.25\times$ bonus for holding the World Record (#1)**:

### Track Score Formula:
$$S_{i,k} = \omega_k \times 100.0 \times R(\text{Rank}_{i,k}) \times \mathbb{I}_{\text{WR}}(1.25)$$

Where:
$$R(\text{Rank}_{i,k}) = \frac{1}{1 + 0.6 \cdot \ln(\text{Rank}_{i,k})}$$

$$\mathbb{I}_{\text{WR}} = \begin{cases} 1.25 & \text{if } \text{Rank}_{i,k} = 1 \text{ (World Record)} \\ 1.00 & \text{if } \text{Rank}_{i,k} \ge 2 \end{cases}$$

### Why Logarithmic Scaling?
In a competitive game, finishing 2nd on a 4.5 million player map is often within a few milliseconds of the World Record. Under a reciprocal formula like $100/\text{Rank}$, 2nd place loses 50% of the points immediately. Logarithmic scaling ensures top podium finishes stay competitive while rewarding the driver holding the #1 spot.

* **Rank 1 (World Record):** Receives **$125.0\text{ base points}$** ($1.25\times$ bonus).
* **Rank 2:** Receives **$70.6\text{ base points}$**.
* On a 4.5M track ($\omega = 1.30$), Rank 2 gives:
  $$S = 1.30 \times 70.6 = \mathbf{91.8\text{ points}}$$
  This properly outscores a 1st place finish on a track with 7,350 players ($\omega = 0.80 \times 125.0 = \mathbf{99.5\text{ points}}$ vs $80.0\text{ base}$), reflecting the immense depth of competition.

### Base Points by Placement ($\omega = 1.00$):

| Placement | Log Factor $R(\text{Rank})$ | WR Bonus | Base Points ($S / \omega$) |
|:---:|:---:|:---:|:---:|
| **Rank 1 (World Record)** | $1.000$ | **$1.25\times$** | **$125.00\text{ pts}$** |
| **Rank 2 (2nd Place)** | $0.706$ | $1.00\times$ | **$70.63\text{ pts}$** |
| **Rank 3 (3rd Place)** | $0.603$ | $1.00\times$ | **$60.27\text{ pts}$** |
| **Rank 5 (Top 5)** | $0.509$ | $1.00\times$ | **$50.87\text{ pts}$** |
| **Rank 10 (Top 10)** | $0.420$ | $1.00\times$ | **$41.99\text{ pts}$** |
| **Rank 25 (Top 25)** | $0.341$ | $1.00\times$ | **$34.11\text{ pts}$** |
| **Rank 50 (Top 50)** | $0.299$ | $1.00\times$ | **$29.89\text{ pts}$** |

---

## Step 3: Dual Engine Aggregation

### Engine 1: Peak Quality Index (PQI, Top 6 Tracks)
Evaluates your best 6 track scores across the full 6-track peak ceiling window ($W_6 = \sum_{r=1}^6 0.85^{r-1} \approx 4.1523$):
$$\text{PQI} = \frac{\sum_{r=1}^{\min(6, m)} (0.85)^{r-1} \cdot S_{(r)}}{\sum_{r=1}^{6} (0.85)^{r-1}} = \frac{\sum_{r=1}^{\min(6, m)} (0.85)^{r-1} \cdot S_{(r)}}{4.1523}$$

* Drivers with 6 or more driven tracks receive their exact weighted average across their best 6 scores.
* Drivers with fewer than 6 tracks have unplayed slots zero-padded, smoothly scaling with proven peak capability without artificial prior inflation.

### Engine 2: Versatility & Depth Index (VDI, Top 15 Tracks)
Evaluates your sustained competitive excellence and versatility across the full 15-track depth window ($W_{15} = \sum_{r=1}^{15} 0.90^{r-1} \approx 7.9411$):
$$\text{VDI} = \frac{\sum_{r=1}^{\min(15, m)} (0.90)^{r-1} \cdot S_{(r)}}{\sum_{r=1}^{15} (0.90)^{r-1}} = \frac{\sum_{r=1}^{\min(15, m)} (0.90)^{r-1} \cdot S_{(r)}}{7.9411}$$

* Drivers with 15 or more tracks receive their full weighted average across their top 15 scores.
* Unplayed tracks in the 15-track window score $0.0$, strictly rewarding breadth and depth across the ecosystem.

---

## Step 4: Engine 3: Global Skill Index (GSI Synthesis)

Standardizes PQI and VDI into Z scores against the active competitor population ($\ge 5$ tracks), then weights them 70% Peak Ceiling / 30% Sustained Depth:

$$\text{GSI} = 1000.0 + 200.0 \cdot \left( 0.70 \cdot Z_{\text{PQI}} + 0.30 \cdot Z_{\text{VDI}} \right)$$

### Understanding GSI Score Ranges:
* **👑 3,500+ GSI (World Championship Tier):** Drivers who dominate world records across multiple high traffic campaign and community tracks.
* **🏆 2,000–3,499 GSI (Podium Contenders):** Top tier drivers capable of winning major world records and consistently finishing top 3 globally.
* **⚡ 1,500–1,999 GSI (Specialists and Top 50 Drivers):** Highly skilled drivers holding top 5 finishes on competitive campaign or community tracks.
* **👥 1,000–1,499 GSI (Active Competitive Median):** Solid drivers who regularly set verified times across multiple tracks.

---

## 3. 2-Domain Macro-Discipline Engine (v10.2 Dual-Axis Mastery)

All 78 tracks are organized into two balanced macro-disciplines:

1. **Fullspeed Discipline (36 Tracks):**
   * **Fullspeed (FS):** 31 tracks
   * **Fakespeed:** 5 tracks
   * **Total:** 36 Tracks

2. **Technical Discipline (42 Tracks):**
   * **Tech:** 14 tracks
   * **Speedtech:** 14 tracks
   * **Speedfun:** 14 tracks
   * **Total:** 42 Tracks

### Discipline Rating Formula:
For each domain $D \in \{\text{Fullspeed}, \text{Technical}\}$, a player's rating evaluates their **Top 6 best runs** ($K=6$) with harmonic decay ($\gamma = 0.85$) and full-window normalization:

$$\text{Rating}(i, D) = \frac{\sum_{r=1}^{\min(6, m_D)} (0.85)^{r-1} \cdot S_{(r)}}{\sum_{r=1}^{6} (0.85)^{r-1}} = \frac{\sum_{r=1}^{\min(6, m_D)} (0.85)^{r-1} \cdot S_{(r)}}{4.1523}$$

### Discipline Bias Ratio & Archetypes:
$$\text{Bias}(i) = \frac{\text{Rating}(i, \text{Fullspeed})}{\text{Rating}(i, \text{Fullspeed}) + \text{Rating}(i, \text{Technical})}$$

* **Fullspeed Specialist:** $\text{Bias}(i) \ge 0.70$ and $\ge 4$ Fullspeed tracks driven.
* **Technical Specialist:** $\text{Bias}(i) \le 0.30$ and $\ge 4$ Technical tracks driven.
* **Generalist:** $0.30 < \text{Bias}(i) < 0.70$ and $\ge 4$ tracks driven in both domains.
* **Player:** Default archetype for $< 4$ tracks per domain.

---

## 4. Player Classification (Ecosystem Bias)

Separate from driving physics discipline (Fullspeed vs Tech), the system classifies players by where they earn their points:

$$\text{Domain Bias}(i) = \frac{\sum_{k \in \text{Main}} S_{i,k}}{\sum_{k \in \text{Main}} S_{i,k} + \sum_{k \in \text{Community}} S_{i,k}}$$

* **Main Specialist:** $\text{Domain Bias}(i) \ge 0.70$ (Earns $\ge 70\%$ of points on official campaign tracks).
* **Community Specialist:** $\text{Domain Bias}(i) \le 0.30$ (Earns $\ge 70\%$ of points on community tracks).
* **All Rounder:** $0.30 < \text{Domain Bias}(i) < 0.70$ (Balanced points across both campaign and community tracks).
