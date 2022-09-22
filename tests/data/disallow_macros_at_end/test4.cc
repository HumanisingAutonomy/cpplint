// Copyright 2014 Your Company.
class OuterClass1 {
 private:
  struct InnerClass1 {
   private:
    DISALLOW_IMPLICIT_CONSTRUCTORS(InnerClass1);
  };
  DISALLOW_IMPLICIT_CONSTRUCTORS(OuterClass1);
};
struct OuterClass2 {
 private:
  class InnerClass2 {
   private:
    DISALLOW_IMPLICIT_CONSTRUCTORS(InnerClass2);
    // comment
  };

  DISALLOW_IMPLICIT_CONSTRUCTORS(OuterClass2);

  // comment
};
void Func() {
  struct LocalClass {
   private:
    DISALLOW_IMPLICIT_CONSTRUCTORS(LocalClass);
  } variable;
}

