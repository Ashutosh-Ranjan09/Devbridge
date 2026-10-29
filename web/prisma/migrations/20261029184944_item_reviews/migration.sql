-- CreateTable
CREATE TABLE "ItemReview" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "verificationId" TEXT NOT NULL,
    "itemKey" TEXT NOT NULL,
    "mark" TEXT NOT NULL,
    "note" TEXT NOT NULL,
    "reviewedById" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ItemReview_verificationId_fkey" FOREIGN KEY ("verificationId") REFERENCES "Verification" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "ItemReview_reviewedById_fkey" FOREIGN KEY ("reviewedById") REFERENCES "User" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE INDEX "ItemReview_verificationId_itemKey_idx" ON "ItemReview"("verificationId", "itemKey");
