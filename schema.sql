CREATE TABLE `comments` (
	`id` text PRIMARY KEY NOT NULL,
	`lesson_id` text NOT NULL,
	`student_id` text NOT NULL,
	`body` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_comments_lesson` ON `comments` (`lesson_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `grades` (
	`lesson_id` text NOT NULL,
	`student_id` text NOT NULL,
	`grade` integer NOT NULL,
	`feedback` text DEFAULT '' NOT NULL,
	`updated_at` text NOT NULL,
	PRIMARY KEY(`lesson_id`, `student_id`),
	CONSTRAINT "grade_range" CHECK("grades"."grade" BETWEEN 1 AND 12)
);
--> statement-breakpoint
CREATE TABLE `lesson_overrides` (
	`id` text PRIMARY KEY NOT NULL,
	`date` text NOT NULL,
	`class_name` text NOT NULL,
	`subject` text NOT NULL,
	`topic` text NOT NULL,
	`start_time` text NOT NULL,
	`end_time` text NOT NULL,
	`position` integer NOT NULL,
	`room` text DEFAULT '' NOT NULL,
	`online` integer DEFAULT 0 NOT NULL,
	`deleted` integer DEFAULT 0 NOT NULL,
	`version` integer DEFAULT 1 NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_lessons_date` ON `lesson_overrides` (`date`);--> statement-breakpoint
CREATE TABLE `student_notes` (
	`lesson_id` text NOT NULL,
	`student_id` text NOT NULL,
	`body` text NOT NULL,
	`updated_at` text NOT NULL,
	PRIMARY KEY(`lesson_id`, `student_id`)
);
