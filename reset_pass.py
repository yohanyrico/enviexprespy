import bcrypt
nueva = bcrypt.hashpw('oscarb123'.encode(), bcrypt.gensalt()).decode()
print(nueva)