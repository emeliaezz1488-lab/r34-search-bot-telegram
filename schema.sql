-- MariaDB / MySQL Schema for NSFW Telegram Bot
CREATE DATABASE IF NOT EXISTS `nsfw_bot` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `nsfw_bot`;

CREATE TABLE IF NOT EXISTS `chats_settings` (
  `chat_id` VARCHAR(64) NOT NULL,
  `key` VARCHAR(64) NOT NULL,
  `value` TEXT NOT NULL,
  PRIMARY KEY (`chat_id`, `key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `known_chats` (
  `chat_id` BIGINT NOT NULL,
  `title` VARCHAR(255) NOT NULL DEFAULT '',
  `type` VARCHAR(32) NOT NULL DEFAULT 'group',
  `last_active` BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (`chat_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `blacklist` (
  `entity_id` BIGINT NOT NULL,
  PRIMARY KEY (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `bot_kv` (
  `key` VARCHAR(64) NOT NULL,
  `value` TEXT NOT NULL,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
