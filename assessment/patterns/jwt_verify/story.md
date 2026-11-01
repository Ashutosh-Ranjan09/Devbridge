The {service_label} trusts requests that carry a signed token from the login service. Until
now a library checked the tokens; it is being removed, and the check has to be written
with the standard library alone. Every request depends on it, so a token that should be
refused must never get through.
