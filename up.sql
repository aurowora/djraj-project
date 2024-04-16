CREATE TABLE `categories`
(
    `id`         INTEGER UNSIGNED NOT NULL AUTO_INCREMENT,
    `cat_name`   VARCHAR(64)      NOT NULL,
    `cat_desc`   VARCHAR(128)     NULL,
    `parent_cat` INTEGER UNSIGNED NULL,
    `avatar`     varchar(128) null,
    CONSTRAINT `pk_categories_id` PRIMARY KEY (`id`),
    CONSTRAINT `fk_cat_parent_ref` FOREIGN KEY (`parent_cat`) REFERENCES `categories` (`id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX idx_cat_name ON `categories` (`cat_name`);

-- SHOW CREATE TABLE loginTable (mostly jerron)
CREATE TABLE `loginTable`
(
    `id`       int unsigned NOT NULL AUTO_INCREMENT,
    `MYUSER`   varchar(64)  NOT NULL,
    `PASSWORD` varchar(128) NOT NULL,
    `display_name` VARCHAR(64) NOT NULL,
    `flags`    int unsigned NOT NULL DEFAULT '0',
    CONSTRAINT `pk_user_id` PRIMARY KEY (`id`),
    CONSTRAINT `ck_user_name` UNIQUE (`MYUSER`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

-- SHOW CREATE TABLE threadsTable (mostly jerron)
CREATE TABLE `threadsTable`
(
    `threadID`  int unsigned NOT NULL AUTO_INCREMENT,
    `parent_cat` int unsigned NOT NULL,
    `userID`    int unsigned NOT NULL,
    `title`     varchar(100) NOT NULL,
    `content`   text         NOT NULL,
    `createdAt` timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `flags`     int unsigned NOT NULL DEFAULT '0',
    CONSTRAINT `pk_threads_id` PRIMARY KEY (`threadID`),
    CONSTRAINT `fk_threads_parent_cat` FOREIGN KEY (`parent_cat`) REFERENCES `categories` (`id`),
    CONSTRAINT `fk_author` FOREIGN KEY (`userID`) REFERENCES `loginTable` (`id`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX idx_created_at ON `threadsTable` (`createdAt`);

CREATE TABLE `threadAttachments`
(
    `id` int unsigned not null auto_increment,
    `thread` int unsigned not null,
    `filename` varchar(128) not null,
    `author` int unsigned not null,
    `createdAt` timestamp not null default CURRENT_TIMESTAMP,
    constraint `pk_thread_attachments_id` primary key (`id`),
    constraint `fk_thread_attachments_thr` foreign key (`thread`) references `threadsTable` (`threadID`),
    constraint `fk_thread_attachments_author` foreign key (`author`) references `loginTable` (`id`)
);

-- SHOW CREATE TABLE postsTable (mostly jerron)
CREATE TABLE `postsTable`
(
    `postID`    int unsigned NOT NULL AUTO_INCREMENT,
    `threadID`  int unsigned NOT NULL,
    `userID`    int unsigned NOT NULL,
    `content`   text         NOT NULL,
    `createdAt` timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `flags`     int unsigned NOT NULL DEFAULT '0',
    CONSTRAINT `pk_posts_id` PRIMARY KEY (`postID`),
    CONSTRAINT `fk_posts_thread` FOREIGN KEY (`threadID`) REFERENCES `threadsTable` (`threadID`),
    CONSTRAINT `fk_posts_user` FOREIGN KEY (`userID`) REFERENCES `loginTable` (`id`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX idx_posts_table ON `postsTable` (`createdAt`);

CREATE TABLE `postsAttachments`
(
    `id` int unsigned not null auto_increment,
    `post` int unsigned not null,
    `filename` varchar(128) not null,
    `author` int unsigned not null,
    `createdAt` timestamp not null default CURRENT_TIMESTAMP,
    constraint `pk_posts_attachments_id` primary key (`id`),
    constraint `fk_posts_attachments_post` foreign key (`post`) references `postsTable` (`postID`),
    constraint `fk_posts_attachments_author` foreign key (`author`) references `loginTable` (`id`)
);