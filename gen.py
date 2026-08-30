# gen.py
import random
import string

ADMIN_MAX_GENS = 500000

LETTRES = string.ascii_lowercase
CHIFFRES = string.digits

def generer_tous_prononcables_batch(length, game_id, state_index, batch_size, use_nums):
    voyelles = "aeiouy"
    consonnes = "bcdfghjklmnpqrstvwxz"
    batch = []
    
    for _ in range(batch_size):
        pseudo = ""
        for i in range(length):
            if i % 2 == 0:
                pseudo += random.choice(consonnes)
            else:
                pseudo += random.choice(voyelles)
        
        if use_nums and length > 1:
            pos = random.randint(1, min(2, length))
            pseudo = pseudo[:-pos] + str(random.randint(0, 9)) * pos
            
        batch.append(pseudo)
    return batch


def preparer_combinaisons_classiques_batch(length, use_random, use_nums, game_id, state_index, batch_size, prefixe=""):
    chars = LETTRES + (CHIFFRES if use_nums else "")
    batch = []
    effective_length = max(1, length - len(prefixe))
    
    seen = set()
    attempts = 0
    while len(batch) < batch_size and attempts < batch_size * 3:
        attempts += 1
        rand_part = "".join(random.choices(chars, k=effective_length))
        pseudo = prefixe + rand_part
        if pseudo not in seen:
            seen.add(pseudo)
            batch.append(pseudo)
            
    # Fallback si doublons en random pur atteint
    while len(batch) < batch_size:
        rand_part = "".join(random.choices(chars, k=effective_length))
        batch.append(prefixe + rand_part)
        
    return batch


def generer_toutes_possibilites_batch(length, game_id, state_index, batch_size, prefixe=""):
    chars = LETTRES + CHIFFRES
    base = len(chars)
    batch = []
    effective_length = max(1, length - len(prefixe))
    
    for i in range(batch_size):
        curr_index = state_index + i
        temp_chars = []
        val = curr_index
        for _ in range(effective_length):
            temp_chars.append(chars[val % base])
            val //= base
        
        brute_part = "".join(reversed(temp_chars))
        pseudo = prefixe + brute_part
        batch.append(pseudo)
        
    return batch
