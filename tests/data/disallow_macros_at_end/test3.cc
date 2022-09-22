// Copyright 2014 Your Company.
class OuterClass1 {
 private:
  struct InnerClass1 {
   private:
    DISALLOW_COPY_AND_ASSIGN(InnerClass1);
  };
  DISALLOW_COPY_AND_ASSIGN(OuterClass1);
};
struct OuterClass2 {
 private:
  class InnerClass2 {
   private:
    DISALLOW_COPY_AND_ASSIGN(InnerClass2);
    // comment
  };

  DISALLOW_COPY_AND_ASSIGN(OuterClass2);

  // comment
};
void Func() {
  struct LocalClass {
   private:
    DISALLOW_COPY_AND_ASSIGN(LocalClass);
  } variable;
}

