-- CreateTable
CREATE TABLE "LoginFailure" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "email" TEXT NOT NULL,
    "at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE INDEX "LoginFailure_email_at_idx" ON "LoginFailure"("email", "at");
