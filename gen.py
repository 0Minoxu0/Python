import random
import string

ADMIN_MAX_GENS = 500000

# Alphabet de base
LETTRES = string.ascii_lowercase
CHIFFRES = string.digits

def generer_tous_prononcables_batch(length, game_id, state_index, batch_size, use_nums):
    # Mode 1 : Prononçable (Alternance consonne/voyelle)
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
            # Ajout d'un chiffre aléatoire sur les derniers caractères si demandé
            pos = random.randint(1, min(2, length))
            pseudo = pseudo[:-pos] + str(random.randint(0, 9)) * pos
            
        batch.append(pseudo)
    return batch


def preparer_combinaisons_classiques_batch(length, use_random, use_nums, game_id, state_index, batch_size, prefixe=""):
    # Mode 2 : Random pur de la taille demandée (corrigé pour être unique à chaque appel)
    chars = LETTRES + (CHIFFRES if use_nums else "")
    batch = []
    
    effective_length = max(1, length - len(prefixe))
    
    for _ in range(batch_size):
        rand_part = "".join(random.choices(chars, k=effective_length))
        pseudo = prefixe + rand_part
        batch.append(pseudo)
        
    return batch


def generer_toutes_possibilites_batch(length, game_id, state_index, batch_size, prefixe=""):
    # Mode 3 : Bruteforce séquentiel (reste inchangé car il doit progresser dans l'ordre)
    chars = LETTRES + CHIFFRES
    base = len(chars)
    batch = []
    
    effective_length = max(1, length - len(prefixe))
    
    for i in range(batch_size):
        curr_index = state_index + i
        # Conversion de l'index en base variable (style Excel / bruteforce)
        temp_chars = []
        val = curr_index
        for _ in range(effective_length):
            temp_chars.append(chars[val % base])
            val //= base
        
        brute_part = "".join(reversed(temp_chars))
        pseudo = prefixe + brute_part
        batch.append(pseudo)
        
    return batch