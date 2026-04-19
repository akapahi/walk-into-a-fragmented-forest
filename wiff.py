import pygame
import random
import math
import colorsys
import socket
from pythonosc import udp_client

OSC_IP   = "127.0.0.1"  # change to receiving device's IP if needed
OSC_PORT = 4560

osc = udp_client.SimpleUDPClient(OSC_IP, OSC_PORT)
# ───────────────── CONFIG ─────────────────
WIDTH, HEIGHT = 1000, 600
FPS = 30

NUM_SPECIES = 5

BASE_DEATH = 0.0008
CNDD_STRENGTH = 0.15

UPDATE_INTERVAL = 100
SEEDLING_DURATION = 9000
DYING_DURATION = 9000

dt = UPDATE_INTERVAL / 1000.0

MODE_OPTION_1 = 1
MODE_OPTION_3 = 3
mode = MODE_OPTION_3

# ───────────────── CONFIG ─────────────────
RING_SPEED_MIN_RANGE = (0.3, 0.6)
RING_SPEED_MAX_RANGE = (0.6, 0.9)
RING_INTERVAL_RANGE  = (1200, 2500)  # ms
# ───────────────── UDP ─────────────────
UDP_PORT = 4210

def send_osc_event(node_id, event, **kwargs):
    address = f"/forest/{event}"
    msg = [node_id]
    for v in kwargs.values():
        if isinstance(v, list):
            msg.extend(v)
        else:
            msg.append(v)
    osc.send_message(address, msg)

def send_config(i):
    spd_min   = round(random.uniform(*RING_SPEED_MIN_RANGE), 2)
    spd_max   = round(random.uniform(*RING_SPEED_MAX_RANGE), 2)
    interval  = random.randint(*RING_INTERVAL_RANGE)
    panel_type = 1 if i in EXTERIOR_NODES else 0
    packet    = f"CFG,{i},{spd_min},{spd_max},{interval},{panel_type}"
    sock.sendto(packet.encode(), (UDP_IP, UDP_PORT))

def get_broadcast_address():
    try:
        # connect to external address to find the active interface IP
        # no data is actually sent
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        # assume /24 subnet — replace last octet with 255
        parts = local_ip.split(".")
        broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
        print(f"Local IP: {local_ip} → Broadcast: {broadcast}")
        return broadcast

    except Exception as e:
        print(f"Could not detect IP, falling back to 255.255.255.255 — {e}")
        return "255.255.255.255"

UDP_IP = get_broadcast_address()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# ───────────────── POSITIONS ─────────────────
positions = {
    # far right column
    1:  (950, 80),
    2:  (950, 140),

    # upper middle-right cluster
    4:  (830, 80),
    5:  (760, 80),
    6:  (760, 140),
    7:  (830, 200),
    12: (700, 140),
    13: (640, 80),

    # middle right
    3:  (950, 310),
    8:  (860, 310),
    9:  (700, 310),

    # middle band
    14: (600, 175),
    15: (510, 120),
    18: (530, 270),
    19: (610, 310),

    # left-middle
    16: (400, 175),
    17: (310, 210),
    20: (330, 380),

    # bottom
    10: (900, 450),
    11: (800, 450),
    21: (430, 470),
    22: (240, 470),
}


EXTERIOR_NODES = {10, 11, 17, 20, 21, 22}
INTERIOR_NODES = set(positions.keys()) - EXTERIOR_NODES

def compute_neighbors(positions, threshold=180):
    neighbors = {i: [] for i in positions}
    for i in positions:
        for j in positions:
            if i != j and math.dist(positions[i], positions[j]) < threshold:
                neighbors[i].append(j)
    return neighbors

neighbors = compute_neighbors(positions)

# ───────────────── COLORS ─────────────────
colors = {}
for i in range(NUM_SPECIES):
    hue = i / NUM_SPECIES
    rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
    colors[i] = tuple(int(c * 255) for c in rgb)

species_list = list(range(NUM_SPECIES))

# ───────────────── INIT ─────────────────
nodes = {
    i: {
        "state":       "mature",
        "species":     random.choice(species_list),
        "age":         0,
        "seedlings":   None,
        "winner":      None,
        "seed_start":  0,
        "death_start": 0
    } for i in positions
}

# ───────────────── HELPERS ─────────────────
def neighbor_counts(i):
    counts = {}
    for j in neighbors[i]:
        if nodes[j]["state"] == "mature":
            s = nodes[j]["species"]
            if s is not None:
                counts[s] = counts.get(s, 0) + 1
    return counts

def weighted_choice(counts):
    choices = []
    for s, c in counts.items():
        choices += [s] * c
    return random.choice(choices) if choices else random.choice(species_list)

def inverse_weight_choice(counts):
    weights = {s: 1 / (counts.get(s, 0) + 1) for s in species_list}
    total   = sum(weights.values())
    r       = random.random() * total
    acc     = 0
    for s, w in weights.items():
        acc += w
        if r < acc:
            return s
    return random.choice(species_list)

def mixed_choice(counts):
    return weighted_choice(counts) if random.random() < 0.7 else inverse_weight_choice(counts)

def compute_pressure(i, species):
    if species is None:
        return 0
    neigh = neighbors[i]
    same  = sum(1 for j in neigh
                if nodes[j]["state"] == "mature" and nodes[j]["species"] == species)
    return same / max(len(neigh), 1)

# ───────────────── UDP PACKET ─────────────────
def build_packet_for_node(i):
    node = nodes[i]

    if node["state"] == "mature":
        s = node["species"] if node["species"] is not None else 0
        return f"{i},0,{s},-1,-1,-1,-1"

    elif node["state"] == "dying":
        s = node["species"] if node["species"] is not None else 0
        return f"{i},2,{s},-1,-1,-1,-1"

    elif node["state"] == "seedling":
        if node["seedlings"] is None or node["winner"] is None:
            return f"{i},0,0,-1,-1,-1,-1"
        s = [seed["species"] for seed in node["seedlings"]]
        return f"{i},1,{node['winner']},{s[0]},{s[1]},{s[2]},{s[3]}"

# ───────────────── UPDATE ─────────────────
def update_system():
    now = pygame.time.get_ticks()

    for i, node in nodes.items():

        if node["state"] == "mature":
            if node["species"] is None:
                node["species"] = random.choice(species_list)
                continue

            pressure   = compute_pressure(i, node["species"])
            death_prob = BASE_DEATH + CNDD_STRENGTH * (pressure ** 2)

            if random.random() < death_prob * dt:
                node["state"]       = "dying"
                node["death_start"] = now
                send_osc_event(i, "death", species=node["species"])

        elif node["state"] == "dying":
            if now - node["death_start"] > DYING_DURATION:

                counts    = neighbor_counts(i)
                seedlings = []

                for _ in range(4):
                    s = weighted_choice(counts) if mode == MODE_OPTION_1 else mixed_choice(counts)
                    if s is None:
                        s = random.choice(species_list)
                    seedlings.append({"species": s})

                node["state"]      = "seedling"
                node["seedlings"]  = seedlings
                node["seed_start"] = now
                node["species"]    = None

                competing = [s["species"] for s in seedlings]
                send_osc_event(i, "seedling", seedlings=competing)

                scores = []
                for seed in seedlings:
                    p = compute_pressure(i, seed["species"])
                    scores.append((seed["species"], 1 - p))

                total          = sum(sc for _, sc in scores)
                node["winner"] = None

                if total > 0:
                    r   = random.random() * total
                    acc = 0
                    for s, score in scores:
                        acc += score
                        if r < acc:
                            node["winner"] = s
                            break

                if node["winner"] is None:
                    node["winner"] = random.choice(species_list)

        elif node["state"] == "seedling":
            if now - node["seed_start"] > SEEDLING_DURATION:
                node["state"]     = "mature"
                node["species"]   = node["winner"] if node["winner"] is not None else random.choice(species_list)
                node["seedlings"] = None
                node["winner"]    = None
                send_osc_event(i, "mature", species=node["species"])
                send_config(i)
# ───────────────── DRAW ─────────────────
def draw(screen):
    screen.fill((10, 15, 10))
    font    = pygame.font.SysFont(None, 18)
    font_id = pygame.font.SysFont(None, 15)
    mouse   = pygame.mouse.get_pos()
    now     = pygame.time.get_ticks()

    # ── broadcast IP indicator (top left) ──
    ip_surf = font.render(f"Broadcasting → {UDP_IP}:{UDP_PORT}", True, (60, 100, 60))
    screen.blit(ip_surf, (10, 10))

    for i, (x, y) in positions.items():
        node = nodes[i]

        if node["state"] == "mature" and node["species"] is not None:
            pressure   = compute_pressure(i, node["species"])
            death_prob = BASE_DEATH + CNDD_STRENGTH * (pressure ** 2)
        else:
            pressure   = 0
            death_prob = 0

        # ── Draw node ──
        if node["state"] == "mature" and node["species"] is not None:
            pygame.draw.circle(screen, colors[node["species"]], (x, y), 12)

        elif node["state"] == "dying":
            s = node["species"]
            if s is not None:
                t   = min((now - node["death_start"]) / DYING_DURATION, 1)
                col = tuple(int(c * (1 - t)) for c in colors[s])
                pygame.draw.circle(screen, col, (x, y), max(2, int(12 * (1 - t))))

        elif node["state"] == "seedling":
            if node["seedlings"] is not None:
                offsets = [(-8, -8), (8, -8), (-8, 8), (8, 8)]
                for seed, (dx, dy) in zip(node["seedlings"], offsets):
                    if seed["species"] is not None:
                        pygame.draw.circle(screen, colors[seed["species"]],
                                           (x + dx, y + dy), 4)

        # ── Node ID (always visible) ──
        id_surf = font_id.render(str(i), True, (160, 160, 160))
        screen.blit(id_surf, (x + 14, y + 6))

        # ── Hover debug ──
        if math.dist(mouse, (x, y)) < 15:
            pygame.draw.circle(screen, (255, 255, 255), (x, y), 16, 1)

            for j in neighbors[i]:
                pygame.draw.line(screen, (80, 120, 80), (x, y), positions[j], 2)

            state_char = {"mature": "M", "dying": "D", "seedling": "S"}[node["state"]]
            txt = f"{i} | {state_char} p:{pressure:.2f} d:{death_prob:.2f}"
            screen.blit(font.render(txt, True, (255, 255, 255)), (x + 15, y - 10))

# ───────────────── MAIN ─────────────────
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Kadumane Forest Simulation")
clock = pygame.time.Clock()

last_update = pygame.time.get_ticks()

running = True
while running:
    clock.tick(FPS)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    now = pygame.time.get_ticks()

    update_system()

    while now - last_update > UPDATE_INTERVAL:
        for i in nodes:
            packet = build_packet_for_node(i)
            if packet:
                sock.sendto(packet.encode(), (UDP_IP, UDP_PORT))
        last_update += UPDATE_INTERVAL

    draw(screen)
    pygame.display.flip()

pygame.quit()