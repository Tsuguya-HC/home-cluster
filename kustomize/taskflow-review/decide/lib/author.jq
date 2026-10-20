def repo: .repository_url | capture("/repos/(?<r>[^/]+/[^/]+)$").r;
def permission($writers):
  (repo | ascii_downcase) as $r | .user.login as $u
  | first($writers[] | select((.repo | ascii_downcase) == $r and .login == $u) | .permission) // null;
def author($issuer; $writers):
  if .user.type == "Bot" then
    (if .user.id == $issuer then "app" else null end)
  elif .user.type != "User" then null
  elif (.author_association | IN("OWNER", "MEMBER", "COLLABORATOR")) then "human"
  elif permission($writers) != null then "human"
  else null end;
