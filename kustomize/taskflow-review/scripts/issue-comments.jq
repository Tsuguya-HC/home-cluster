# public リポでは誰でも書けるので、リポの関係者のものだけ通す。
.[] | select(.author_association == "OWNER" or .author_association == "MEMBER" or .author_association == "COLLABORATOR") | {author: .user.login, body}
