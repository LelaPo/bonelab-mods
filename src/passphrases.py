import random

WORDS = [
    "amber", "arrow", "atlas", "blaze", "bravo", "breeze", "cabin", "canyon", 
    "cedar", "cipher", "clover", "comet", "coral", "crater", "crystal", "delta", 
    "drift", "echo", "falcon", "flame", "forest", "frost", "galaxy", "glacier", 
    "harbor", "haven", "hawk", "horizon", "island", "jaguar", "jungle", "laser", 
    "lemon", "lotus", "lunar", "matrix", "meteor", "mirage", "nebula", "ninja", 
    "oasis", "ocean", "orbit", "ozone", "panther", "phantom", "phoenix", "pilot", 
    "planet", "polar", "prism", "pulse", "radar", "raven", "reef", "river", 
    "rocket", "safari", "shadow", "shield", "siren", "solar", "spark", "spiral", 
    "storm", "summit", "sunset", "tiger", "timber", "titan", "torch", "tundra", 
    "valley", "vapor", "velvet", "viper", "vortex", "voyage", "whisper", "winter"
]

def generate_passphrase() -> str:
    return "-".join(random.sample(WORDS, 3))